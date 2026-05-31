# ─────────────────────────────────────────────────────────────────────────────
#  BB DOF – Depth-of-Field visualiser for Blender
#  Location : Properties ▶ Render ▶ BB DOF
# ─────────────────────────────────────────────────────────────────────────────

bl_info = {
    "name":        "BB DOF",
    "author":      "Blender Bob + Claude.ai",
    "version":     (1, 4, 1),
    "blender":     (4, 2, 0),
    "location":    "Properties › Render › BB DOF",
    "description": "Real-time depth-of-field visualiser",
    "category":    "Render",
}

import bpy
import math
from bpy.props import BoolProperty, FloatProperty, StringProperty, PointerProperty
from bpy.app.handlers import persistent


# ═══════════════════════════════════════════════════════════════════════════════
#  DoF MATHS
# ═══════════════════════════════════════════════════════════════════════════════

def compute_dof_limits(cam_data, cam_obj=None):
    dof   = cam_data.dof
    # If a focus object is set, derive focus distance from world-space positions
    if dof.focus_object and cam_obj:
        import mathutils
        cam_pos  = cam_obj.matrix_world.translation
        foc_pos  = dof.focus_object.matrix_world.translation
        focus    = max((foc_pos - cam_pos).length, 0.001)
    else:
        focus = max(dof.focus_distance, 0.001)
    f     = cam_data.lens / 1000.0
    coc   = cam_data.sensor_width / 1500.0 / 1000.0
    N     = max(dof.aperture_fstop, 0.1)
    H     = (f * f) / (N * coc) + f
    dn    = H + focus - 2.0 * f
    near  = max(0.001, (focus * (H - f)) / dn) if abs(dn) > 1e-9 else 0.001
    df    = H - focus
    far   = (focus * (H - f)) / df if df > 1e-9 else 1e6
    return float(min(near, focus * 0.999)), float(focus), float(max(far, focus * 1.001))



def solve_focus_fstop(near, far, cam_data):
    """
    Inverse DoF solver: given desired near & far limits, return the
    (focus_distance, aperture_fstop) values that produce them exactly.
    """
    f   = cam_data.lens / 1000.0
    coc = cam_data.sensor_width / 1500.0 / 1000.0
    Dn, Df = max(near, 0.001), max(far, near * 1.001)
    # Quadratic: (Dn+Df)*focus^2 - (2*Dn*Df + f*(Dn+Df))*focus + 2*Dn*f*Df = 0
    a = Dn + Df
    b = -(2*Dn*Df + f*(Dn + Df))
    c = 2*Dn*f*Df
    disc = b*b - 4*a*c
    if disc < 0:
        return None, None
    focus = (-b + math.sqrt(max(0, disc))) / (2*a)
    focus = max(focus, Dn * 1.001)
    denom = Df - focus
    H = focus*(Df - f) / denom if denom > 1e-6 else 1e9
    N = (f*f) / ((H - f) * coc) if (H - f) > 1e-9 else 0.1
    return max(0.001, focus), max(0.1, N)


# ═══════════════════════════════════════════════════════════════════════════════
#  MATERIAL / SHADER  (Colors mode)
# ═══════════════════════════════════════════════════════════════════════════════

MAT_NAME = "BB_DOF_Overlay"

def _cam_world_vectors(cam_obj):
    mx = cam_obj.matrix_world
    return (mx.col[3].x, mx.col[3].y, mx.col[3].z), \
           (-mx.col[2].x, -mx.col[2].y, -mx.col[2].z)

def _focus_norm(near, focus, far):
    span = far - near
    return 0.5 if span < 1e-9 else max(0.01, min(0.99, (focus - near) / span))

def _build_material(near, focus, far, cam_obj):
    mat = bpy.data.materials.get(MAT_NAME) or bpy.data.materials.new(MAT_NAME)
    mat.use_nodes = True
    nodes = mat.node_tree.nodes; links = mat.node_tree.links; nodes.clear()
    pos, fwd = _cam_world_vectors(cam_obj)
    fn = _focus_norm(near, focus, far)

    def MN(t, x, y): n = nodes.new(t); n.location = (x, y); return n

    out  = MN("ShaderNodeOutputMaterial", 900,   0); out.target = 'ALL'
    emit = MN("ShaderNodeEmission",       680,   0); emit.inputs["Strength"].default_value = 1.0
    ramp = MN("ShaderNodeValToRGB",       400,   0)
    mrng = MN("ShaderNodeMapRange",       140,   0); mrng.name = "BB_MapRange"; mrng.clamp = False
    dotp = MN("ShaderNodeVectorMath",    -100,   0); dotp.operation = 'DOT_PRODUCT'
    sub  = MN("ShaderNodeVectorMath",    -340,  40); sub.operation  = 'SUBTRACT'
    cp   = MN("ShaderNodeCombineXYZ",   -580,  -40); cp.name  = "BB_CamPos"
    cf   = MN("ShaderNodeCombineXYZ",   -340, -120); cf.name  = "BB_CamFwd"
    geo  = MN("ShaderNodeNewGeometry",  -580,   80)

    for nd, v in ((cp, pos), (cf, fwd)):
        nd.inputs["X"].default_value = v[0]
        nd.inputs["Y"].default_value = v[1]
        nd.inputs["Z"].default_value = v[2]

    mrng.inputs["From Min"].default_value = near
    mrng.inputs["From Max"].default_value = far
    mrng.inputs["To Min"].default_value   = 0.0
    mrng.inputs["To Max"].default_value   = 1.0

    cr = ramp.color_ramp; cr.interpolation = 'LINEAR'
    cr.elements[0].position = 0.0; cr.elements[0].color = (0.9, 0.05, 0.05, 1.0)
    cr.elements[1].position = 1.0; cr.elements[1].color = (0.05, 0.15, 0.9,  1.0)
    g = cr.elements.new(fn);       g.color = (0.05, 0.95, 0.15, 1.0)

    links.new(geo.outputs["Position"],  sub.inputs[0])
    links.new(cp.outputs["Vector"],     sub.inputs[1])
    links.new(sub.outputs["Vector"],    dotp.inputs[0])
    links.new(cf.outputs["Vector"],     dotp.inputs[1])
    links.new(dotp.outputs["Value"],    mrng.inputs["Value"])
    links.new(mrng.outputs["Result"],   ramp.inputs["Fac"])
    links.new(ramp.outputs["Color"],    emit.inputs["Color"])
    links.new(emit.outputs["Emission"], out.inputs["Surface"])
    return mat

def _update_material(near, focus, far, cam_obj):
    mat = bpy.data.materials.get(MAT_NAME)
    if not mat: return
    pos, fwd = _cam_world_vectors(cam_obj)
    fn = _focus_norm(near, focus, far)
    for nd in mat.node_tree.nodes:
        if nd.name == "BB_MapRange":
            nd.inputs["From Min"].default_value = near
            nd.inputs["From Max"].default_value = far
        elif nd.name == "BB_CamPos":
            nd.inputs["X"].default_value = pos[0]
            nd.inputs["Y"].default_value = pos[1]
            nd.inputs["Z"].default_value = pos[2]
        elif nd.name == "BB_CamFwd":
            nd.inputs["X"].default_value = fwd[0]
            nd.inputs["Y"].default_value = fwd[1]
            nd.inputs["Z"].default_value = fwd[2]
        elif nd.type == 'VALTORGB' and len(nd.color_ramp.elements) == 3:
            els = sorted(nd.color_ramp.elements, key=lambda e: e.position)
            els[0].position = 0.0
            els[1].position = max(0.01, min(0.99, fn))
            els[2].position = 1.0


# ═══════════════════════════════════════════════════════════════════════════════
#  DOF PLANE OVERLAY  (GPU draw handler — works in ALL viewport shading modes)
#
#  Draws three coloured, semi-transparent rectangles directly in 3-D space via
#  Blender's GPU module.  No mesh objects are created, so colours are always
#  correct regardless of viewport shading mode.
# ═══════════════════════════════════════════════════════════════════════════════

import gpu
from gpu_extras.batch import batch_for_shader
from mathutils import Vector

_draw_handler = None

# (distance-key, solid-edge RGBA, fill RGBA)
_PLANE_STYLES = [
    ("near",  (0.90, 0.10, 0.10, 1.00), (0.90, 0.10, 0.10, 0.12)),  # red
    ("focus", (1.00, 1.00, 1.00, 1.00), (1.00, 1.00, 1.00, 0.12)),  # white
    ("far",   (0.10, 0.25, 0.90, 1.00), (0.10, 0.25, 0.90, 0.12)),  # blue
]


def _plane_corners(cam_obj, distance, scene):
    """World-space corners of a rectangle perpendicular to the camera axis."""
    mx      = cam_obj.matrix_world
    cam_pos = Vector((mx.col[3].x, mx.col[3].y, mx.col[3].z))
    forward = Vector((-mx.col[2].x, -mx.col[2].y, -mx.col[2].z)).normalized()
    right   = Vector(( mx.col[0].x,  mx.col[0].y,  mx.col[0].z)).normalized()
    up      = Vector(( mx.col[1].x,  mx.col[1].y,  mx.col[1].z)).normalized()
    center  = cam_pos + forward * distance
    fov_h   = cam_obj.data.angle
    aspect  = max(scene.render.resolution_x, 1) / max(scene.render.resolution_y, 1)
    half_w  = distance * math.tan(fov_h / 2) * 1.15
    half_h  = half_w / aspect
    return [
        center + right * half_w + up * half_h,
        center - right * half_w + up * half_h,
        center - right * half_w - up * half_h,
        center + right * half_w - up * half_h,
    ]


def _draw_dof_planes():
    """GPU callback — draws three coloured rectangles in 3-D space."""
    try:
        context = bpy.context
        if not context or not context.scene:
            return
        scene   = context.scene
        props   = scene.bb_dof
        cam_obj = bpy.data.objects.get(props.selected_camera) if props.selected_camera                   else scene.camera
        if not cam_obj or cam_obj.type != 'CAMERA':
            return

        # Don't draw when planes are toggled off
        if not props.planes_active:
            return

        # Don't draw when neither Colors nor Clipping is active
        if not props.colors_active and not props.clipping_active:
            return

        # Don't draw when looking through the camera — planes would be on top of the lens
        for area in context.screen.areas:
            if area.type == 'VIEW_3D':
                if area.spaces[0].region_3d.view_perspective == 'CAMERA':
                    return
                break

        near, focus, far = compute_dof_limits(cam_obj.data, cam_obj)
        draw_far  = min(far, 10_000.0)
        distances = {"near": near, "focus": focus, "far": draw_far}

        shader = gpu.shader.from_builtin('UNIFORM_COLOR')
        gpu.state.depth_test_set('LESS_EQUAL')
        gpu.state.blend_set('ALPHA')
        shader.bind()

        for key, edge_col, fill_col in _PLANE_STYLES:
            corners = _plane_corners(cam_obj, distances[key], scene)
            c = [(v.x, v.y, v.z) for v in corners]

            # Filled quad (two triangles)
            shader.uniform_float("color", fill_col)
            batch_for_shader(shader, 'TRIS',
                {"pos": [c[0], c[1], c[2], c[0], c[2], c[3]]}).draw(shader)

            # Coloured outline
            gpu.state.line_width_set(2.0)
            shader.uniform_float("color", edge_col)
            batch_for_shader(shader, 'LINES',
                {"pos": [c[0], c[1], c[1], c[2], c[2], c[3], c[3], c[0]]}).draw(shader)

    except Exception:
        pass
    finally:
        gpu.state.depth_test_set('NONE')
        gpu.state.blend_set('NONE')
        gpu.state.line_width_set(1.0)


def _register_vis_handler():
    global _draw_handler
    if _draw_handler is None:
        _draw_handler = bpy.types.SpaceView3D.draw_handler_add(
            _draw_dof_planes, (), 'WINDOW', 'POST_VIEW')

def _unregister_vis_handler():
    global _draw_handler
    if _draw_handler is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_draw_handler, 'WINDOW')
        _draw_handler = None


# ── Stubs so callers in depsgraph/operator code remain unchanged ──────────────

def _create_planes(): pass
def _create_planes_timer(): return None
def _remove_planes(): pass
def _position_planes(cam_obj, scene): pass

# ═══════════════════════════════════════════════════════════════════════════════
#  STATE HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

_saved_clip:    dict = {}
_prev_dof_vals:  dict = {}
_syncing_limits: bool = False  # guard: prevents depsgraph sync from re-triggering callbacks


def _get_target_camera(context):
    props = context.scene.bb_dof
    obj   = bpy.data.objects.get(props.selected_camera) if props.selected_camera else None
    if obj is None:
        obj = context.scene.camera
    return obj if (obj and obj.type == 'CAMERA') else None


def _apply_colors(context):
    cam = _get_target_camera(context)
    if not cam: return
    n, fo, fa = compute_dof_limits(cam.data, cam)
    context.view_layer.material_override = _build_material(n, fo, fa, cam)

def _remove_colors(context):
    ovr = context.view_layer.material_override
    if ovr and ovr.name == MAT_NAME:
        context.view_layer.material_override = None

def _apply_clipping(context):
    cam = _get_target_camera(context)
    if not cam: return
    n, fo, fa = compute_dof_limits(cam.data, cam)
    _saved_clip[cam.name] = (cam.data.clip_start, cam.data.clip_end)
    cam.data.clip_start = max(0.001, n)
    cam.data.clip_end   = min(fa, 1e6)

def _restore_clipping(context):
    cam = _get_target_camera(context)
    if cam and cam.name in _saved_clip:
        cam.data.clip_start, cam.data.clip_end = _saved_clip.pop(cam.name)

def _first_3d_space(context):
    for area in context.window.screen.areas:
        if area.type == 'VIEW_3D':
            return area.spaces[0]
    return None

def _ensure_rendered(context):
    """Switch to Rendered view if not already there; save previous mode."""
    props = context.scene.bb_dof
    space = _first_3d_space(context)
    if not space: return
    cur = space.shading.type
    if cur != 'RENDERED':
        props.prev_shading = cur
        space.shading.type = 'RENDERED'
    else:
        props.prev_shading = ""

def _restore_shading(context):
    props = context.scene.bb_dof
    space = _first_3d_space(context)
    if space and props.prev_shading:
        space.shading.type = props.prev_shading
    props.prev_shading = ""


# ═══════════════════════════════════════════════════════════════════════════════
#  OPERATORS
# ═══════════════════════════════════════════════════════════════════════════════

class BB_DOF_OT_ToggleColors(bpy.types.Operator):
    bl_idname = "bb_dof.toggle_colors"; bl_label = "Colors"
    bl_description = "Toggle DoF colour overlay — Red=near · Green=focus · Blue=far"

    def execute(self, context):
        p = context.scene.bb_dof
        p.colors_active = not p.colors_active
        if p.colors_active:
            if p.clipping_active:
                _restore_clipping(context)
                _restore_shading(context)
                p.clipping_active = False
            _apply_colors(context)
            _ensure_rendered(context)
        else:
            _remove_colors(context)
            _restore_shading(context)
        return {'FINISHED'}


class BB_DOF_OT_ToggleClipping(bpy.types.Operator):
    bl_idname = "bb_dof.toggle_clipping"; bl_label = "Clipping"
    bl_description = "Set camera clip planes to DoF near/far limits"

    def execute(self, context):
        p = context.scene.bb_dof
        p.clipping_active = not p.clipping_active
        if p.clipping_active:
            if p.colors_active:
                _remove_colors(context)
                context.scene.bb_dof.prev_shading = ""  # discard saved shading, don't switch
                p.colors_active = False
            _apply_clipping(context)
        else:
            _restore_clipping(context)
        return {'FINISHED'}


class BB_DOF_OT_TogglePlanes(bpy.types.Operator):
    bl_idname = "bb_dof.toggle_planes"; bl_label = "Planes"
    bl_description = "Toggle DoF plane overlays — Red=near · White=focus · Blue=far"

    def execute(self, context):
        context.scene.bb_dof.planes_active = not context.scene.bb_dof.planes_active
        for area in context.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()
        return {'FINISHED'}


class BB_DOF_OT_SelectCamera(bpy.types.Operator):
    """Select as DoF target and look through this camera in the viewport."""
    bl_idname = "bb_dof.select_camera"; bl_label = "Select DoF Camera"
    camera_name: bpy.props.StringProperty()

    def execute(self, context):
        p = context.scene.bb_dof
        if p.clipping_active: _restore_clipping(context)

        p.selected_camera = self.camera_name

        # Switch scene camera and snap viewport to camera view
        cam_obj = bpy.data.objects.get(self.camera_name)
        if cam_obj and cam_obj.type == 'CAMERA':
            context.scene.camera = cam_obj
            for area in context.window.screen.areas:
                if area.type == 'VIEW_3D':
                    area.spaces[0].region_3d.view_perspective = 'CAMERA'
                    break

        cam = _get_target_camera(context)
        if p.colors_active:   _apply_colors(context)
        if p.clipping_active: _apply_clipping(context)

        # Sync sensor slider to the newly selected camera's actual sensor width
        if cam:
            global _syncing_limits
            _syncing_limits = True
            p.sensor_width      = cam.data.sensor_width
            p.prev_sensor_width = cam.data.sensor_width
            _syncing_limits = False

        # Re-create / re-parent planes to the new camera (safe: we're in an operator)
        _create_planes()

        return {'FINISHED'}


# ═══════════════════════════════════════════════════════════════════════════════
#  PANEL
# ═══════════════════════════════════════════════════════════════════════════════

class BB_DOF_PT_Panel(bpy.types.Panel):
    bl_label = "BB DOF"; bl_idname = "RENDER_PT_bb_dof"
    bl_space_type = "PROPERTIES"; bl_region_type = "WINDOW"; bl_context = "render"

    def draw(self, context):
        layout = self.layout
        props  = context.scene.bb_dof
        scene  = context.scene

        # ── Mode buttons ──────────────────────────────────────────────────────
        row = layout.row(align=True); row.scale_y = 1.3
        row.operator("bb_dof.toggle_colors",
                     text="● Colors" if props.colors_active else "Colors",
                     icon='SHADING_RENDERED', depress=props.colors_active)
        row.operator("bb_dof.toggle_clipping",
                     text="● Clipping" if props.clipping_active else "Clipping",
                     icon='CAMERA_DATA', depress=props.clipping_active)

        row2 = layout.row(align=True); row2.scale_y = 1.1
        row2.operator("bb_dof.toggle_planes",
                      text="● Planes" if props.planes_active else "Planes",
                      icon='MESH_PLANE', depress=props.planes_active)

        layout.separator(factor=0.4)

        cameras = [o for o in scene.objects if o.type == 'CAMERA']
        if not cameras:
            layout.label(text="No cameras in scene", icon='ERROR')
            return

        box = layout.box()

        # Mirror _get_target_camera fallback: if nothing explicitly selected, treat scene camera as target
        effective_target = props.selected_camera or (scene.camera.name if scene.camera else "")

        for i, cam_obj in enumerate(cameras):
            is_target = (effective_target == cam_obj.name)
            if i > 0:
                box.separator(factor=0.3)
            col = box.column(align=True)

            # ── Header: [VIEW_CAMERA icon] [name] ─────────────────────────────
            hdr = col.row(align=True)
            op  = hdr.operator(
                "bb_dof.select_camera",
                text   = "",
                icon   = 'VIEW_CAMERA' if is_target else 'VIEW_CAMERA_UNSELECTED',
                emboss = False,
            )
            op.camera_name = cam_obj.name
            hdr.label(text=cam_obj.name)

            
            # ── DOF enable checkbox ───────────────────────────────────────────
            dof_col = col.column(align=True)
            dof_col.enabled = is_target
            dof_col.prop(cam_obj.data.dof, "use_dof", text="Enable DOF")

            # ── Sliders ───────────────────────────────────────────────────────
            sliders = dof_col.column(align=True)
            has_focus_obj = bool(cam_obj.data.dof.focus_object)

            # Near limit
            if has_focus_obj:
                r = sliders.row(align=True); r.enabled = False
                r.label(text="Near: driven by object", icon='OBJECT_DATA')
            else:
                sliders.prop(props, "near_limit", text="Near")

            # Focus distance (middle)
            if has_focus_obj:
                r = sliders.row(align=True); r.enabled = False
                r.label(text=f"Focus: {cam_obj.data.dof.focus_object.name}", icon='OBJECT_DATA')
            else:
                sliders.prop(cam_obj.data.dof, "focus_distance", text="Focus")

            # Far limit
            if has_focus_obj:
                r = sliders.row(align=True); r.enabled = False
                r.label(text="Far: driven by object", icon='OBJECT_DATA')
            else:
                sliders.prop(props, "far_limit", text="Far")

            # F-stop
            sliders.prop(cam_obj.data.dof, "aperture_fstop", text="F-stop")

            # Sensor size (only for target camera)
            if is_target:
                sliders.prop(props, "sensor_width", text="Sensor Size")

        # ── Info readout ──────────────────────────────────────────────────────
        if props.colors_active or props.clipping_active:
            cam = _get_target_camera(context)
            if cam:
                try:
                    n, fo, fa = compute_dof_limits(cam.data, cam)
                    info = layout.column(align=True)
                    info.separator(factor=0.4)
                    info.label(text=f"Near   {n:.3f} m",  icon='TRIA_RIGHT')
                    info.label(text=f"Focus  {fo:.3f} m", icon='DOT')
                    info.label(text=f"Far    {fa:.3f} m", icon='TRIA_LEFT')
                except Exception:
                    pass


# ═══════════════════════════════════════════════════════════════════════════════
#  PROPERTIES
# ═══════════════════════════════════════════════════════════════════════════════

def _update_near_limit(self, context):
    """User dragged the Near slider — solve for focus & fstop, then push to camera."""
    if _syncing_limits:
        return
    cam = _get_target_camera(context)
    if not cam or cam.data.dof.focus_object:
        return
    focus, N = solve_focus_fstop(self.near_limit, self.far_limit, cam.data)
    if focus is not None:
        cam.data.dof.focus_distance  = focus
        cam.data.dof.aperture_fstop  = N


def _update_far_limit(self, context):
    """User dragged the Far slider — solve for focus & fstop, then push to camera."""
    if _syncing_limits:
        return
    cam = _get_target_camera(context)
    if not cam or cam.data.dof.focus_object:
        return
    focus, N = solve_focus_fstop(self.near_limit, self.far_limit, cam.data)
    if focus is not None:
        cam.data.dof.focus_distance  = focus
        cam.data.dof.aperture_fstop  = N


def _update_sensor_width(self, context):
    """User dragged Sensor Size — scale focal length to preserve field of view."""
    if _syncing_limits:
        return
    cam = _get_target_camera(context)
    if not cam:
        return
    old = self.prev_sensor_width
    new = self.sensor_width
    if old > 0.001 and abs(new - old) > 1e-6:
        cam.data.lens = cam.data.lens * (new / old)
    self.prev_sensor_width = new
    cam.data.sensor_width  = new


class BB_DOF_Properties(bpy.types.PropertyGroup):
    colors_active:   BoolProperty(name="Colors Active",    default=False)
    clipping_active: BoolProperty(name="Clipping Active",  default=False)
    planes_active:   BoolProperty(name="Planes Active",    default=True)
    selected_camera: StringProperty(name="Selected Camera", default="")
    prev_shading:    StringProperty(name="Previous Shading", default="")
    near_limit: FloatProperty(
        name="Near", description="Desired near depth-of-field limit",
        default=1.0, min=0.001, soft_max=100.0, unit='LENGTH',
        update=_update_near_limit)
    far_limit: FloatProperty(
        name="Far", description="Desired far depth-of-field limit",
        default=10.0, min=0.001, soft_max=1000.0, unit='LENGTH',
        update=_update_far_limit)
    sensor_width: FloatProperty(
        name="Sensor Size", description="Virtual sensor width — scales focal length to preserve framing",
        default=36.0, min=1.0, soft_max=100.0, unit='CAMERA',
        update=_update_sensor_width)
    prev_sensor_width: FloatProperty(
        name="Previous Sensor Width", default=36.0)


# ═══════════════════════════════════════════════════════════════════════════════
#  HANDLERS
# ═══════════════════════════════════════════════════════════════════════════════

@persistent
def _bb_dof_load_post(filepath):
    """Recreate plane objects after a file is loaded (they don't survive .blend reload)."""
    bpy.app.timers.register(_create_planes_timer, first_interval=0.1)


@persistent
def _bb_dof_update(scene, depsgraph):
    props = scene.bb_dof

    # Auto-enable camera DOF when sliders are moved while use_dof is off
    for cam_obj in (o for o in scene.objects if o.type == 'CAMERA'):
        dof  = cam_obj.data.dof
        prev = _prev_dof_vals.get(cam_obj.name)
        curr = (dof.focus_distance, dof.aperture_fstop)
        if prev is not None and prev != curr and not dof.use_dof:
            dof.use_dof = True
        _prev_dof_vals[cam_obj.name] = curr

    # Resolve target camera
    cam_obj = bpy.data.objects.get(props.selected_camera) if props.selected_camera \
              else scene.camera
    if not cam_obj or cam_obj.type != 'CAMERA':
        return

    try:
        n, fo, fa = compute_dof_limits(cam_obj.data, cam_obj)
        # Keep near_limit/far_limit sliders in sync with the camera
        # (e.g. when the user drags the Focus slider directly)
        # Use guard so writing the props doesn't re-trigger the update callbacks.
        global _syncing_limits
        _syncing_limits = True
        try:
            if abs(props.near_limit - n) > 1e-4:
                props.near_limit = n
            fa_clamped = min(fa, 1e6)
            if abs(props.far_limit - fa_clamped) > 1e-4:
                props.far_limit = fa_clamped
            # Keep sensor slider in sync if sensor_width was changed externally
            if abs(props.sensor_width - cam_obj.data.sensor_width) > 1e-4:
                props.sensor_width      = cam_obj.data.sensor_width
                props.prev_sensor_width = cam_obj.data.sensor_width
        finally:
            _syncing_limits = False
        if props.colors_active:
            _update_material(n, fo, fa, cam_obj)
        if props.clipping_active:
            cam_obj.data.clip_start = max(0.001, n)
            cam_obj.data.clip_end   = min(fa, 1e6)
        # Update plane positions — safe because we only set location/scale,
        # never create datablocks here.
        _position_planes(cam_obj, scene)
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════════════════
#  REGISTRATION
# ═══════════════════════════════════════════════════════════════════════════════

_classes = (
    BB_DOF_Properties,
    BB_DOF_OT_ToggleColors,
    BB_DOF_OT_ToggleClipping,
    BB_DOF_OT_TogglePlanes,
    BB_DOF_OT_SelectCamera,
    BB_DOF_PT_Panel,
)

def register():
    for cls in _classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.bb_dof = PointerProperty(type=BB_DOF_Properties)

    if _bb_dof_update not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(_bb_dof_update)
    if _bb_dof_load_post not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_bb_dof_load_post)

    _register_vis_handler()

    # Defer plane creation so Blender's context is fully ready
    bpy.app.timers.register(_create_planes_timer, first_interval=0.2)

def unregister():
    _unregister_vis_handler()
    _remove_planes()

    if _bb_dof_update in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(_bb_dof_update)
    if _bb_dof_load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_bb_dof_load_post)

    try:
        del bpy.types.Scene.bb_dof
    except Exception:
        pass
    for cls in reversed(_classes):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass
    mat = bpy.data.materials.get(MAT_NAME)
    if mat:
        bpy.data.materials.remove(mat)

if __name__ == "__main__":
    register()
