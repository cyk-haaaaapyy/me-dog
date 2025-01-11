from direct.showbase.ShowBase import ShowBase
from direct.actor.Actor import Actor
from panda3d.core import (
    Point3, WindowProperties, 
    GeomVertexFormat, GeomVertexData,
    Geom, GeomTriangles, GeomVertexWriter, GeomNode, GeomLines,
    GeomTristrips,
    TextNode, AmbientLight, DirectionalLight,
    NodePath, CollisionNode, CollisionBox, CollisionCapsule, BitMask32,
    CollisionTraverser, CollisionHandlerQueue
)
from direct.gui.OnscreenText import OnscreenText
from direct.task import Task
import math
from math import radians
from omegaconf import OmegaConf
from pathlib import Path
import random
from direct.gui.DirectWaitBar import DirectWaitBar

class SandboxGame(ShowBase):
    def __init__(self):
        ShowBase.__init__(self)
        
        # 加载配置
        config_path = Path(__file__).parent / "config.yaml"
        self.cfg = OmegaConf.load(config_path)
        
        # 初始化立方体状态字典（只需要一次）
        self.cube_states = {}
        
        # 设置窗口属性
        props = WindowProperties()
        props.setTitle(self.cfg.window.title)
        props.setSize(self.cfg.window.width, self.cfg.window.height)
        self.win.requestProperties(props)
        
        # 添加光照
        # 环境光
        alight = AmbientLight('alight')
        alight.setColor(tuple(self.cfg.lighting.ambient.color))
        self.alnp = self.render.attachNewNode(alight)
        self.render.setLight(self.alnp)
        
        # 定向光
        dlight = DirectionalLight('dlight')
        dlight.setColor(tuple(self.cfg.lighting.directional.color))
        self.dlnp = self.render.attachNewNode(dlight)
        self.dlnp.setHpr(*self.cfg.lighting.directional.direction)
        self.render.setLight(self.dlnp)
        
        # 角色属性
        self.player_height = self.cfg.player.height
        self.player_width = self.cfg.player.width
        self.player_depth = self.cfg.player.depth
        self.player_heading = self.cfg.player.initial_heading
        
        # 移动和物理相关属性
        self.position = Point3(*self.cfg.player.initial_position)
        self.velocity = Point3(0, 0, 0)
        self.acceleration = self.cfg.physics.acceleration
        self.max_speed = self.cfg.physics.max_speed
        self.deceleration = self.cfg.physics.deceleration
        self.min_speed = self.cfg.physics.min_speed
        
        # 重力相关属性
        self.gravity = self.cfg.physics.gravity
        self.ground_height = self.cfg.physics.ground_height
        self.jump_speed = self.cfg.physics.jump_speed
        
        # 相机控制属性
        self.camera_distance = self.cfg.camera.distance
        self.camera_height = self.cfg.camera.height
        self.camera_pitch = self.cfg.camera.pitch
        self.camera_smooth = self.cfg.camera.smooth
        self.mouse_sensitivity = self.cfg.camera.mouse_sensitivity
        
        # 鼠标位置记录
        self.last_mouse_x = 0
        
        # 添加视角控制属性
        self.camera_heading = 0        # 相机水平角度（相对于角色）
        self.camera_smooth = 0.95      # 相机平滑跟随系数（越大越平滑）
        self.target_camera_heading = 0 # 目标相机角度
        
        # 创建场景元素
        self.create_terrain()              # 创建地形
        self.player = self.create_player() # 创建角色
        self.player.setPos(self.position)  # 设置角色初始位置
        
        # 设置控制
        self.setup_mouse()
        self.setup_keyboard()
        
        # 添加位置文本显示
        self.pos_text = self.add_position_display()
        
        # 初始化相机
        self.update_camera()
        
        # 设置碰撞系统
        self.cTrav = CollisionTraverser()
        self.collision_queue = CollisionHandlerQueue()  # 使用队列处理器
        
        # 为角色添加碰撞检测
        self.setup_player_collision()
        
        # 添加立方体运动任务
        self.taskMgr.add(self.update_cubes_task, "UpdateCubesTask")
        
        # 添加跳跃冷却相关属性
        self.last_jump_time = 0  # 上次跳跃时间
        self.can_jump = True     # 是否可以跳跃
        
        # 添加跳跃冷却显示文本
        self.jump_cooldown_text = self.add_jump_cooldown_display()
        
        # 初始化玩家状态
        self.health = self.cfg.player_status.initial_health
        self.max_health = self.cfg.player_status.max_health
        
        # 创建血条
        self.setup_health_bar()
        
        # 添加游戏状态
        self.game_running = True
        self.start_time = 0
        self.survival_time = 0
        
        # 添加得分显示
        self.score_text = self.add_score_display()
        
        # 开始计时
        self.start_time = globalClock.getRealTime()
        
        self.last_damage_time = 0
        self.damage_cooldown = self.cfg.game_rules.damage.damage_cooldown  # 从配置文件读取冷却时间
        
        # 添加无敌时间相关属性
        self.is_invincible = True
        self.invincible_end_time = 0
        self.invincible_text = self.add_invincible_display()
        
        # 开始无敌时间
        self.start_invincible_time()
        
        # 添加边界警告相关属性
        self.warning_active = False
        self.warning_start_time = 0
        self.warning_text = None
        
        # 添加边界违规相关属性
        self.boundary_violations = []  # 存储违规时间的列表
        self.last_boundary_return_time = 0  # 上次从边界返回的时间
        self.boundary_return_text = self.add_boundary_return_display()
        
        # 添加回血相关属性
        self.last_move_time = 0     # 上次移动时间
        self.last_regen_time = 0    # 上次回血时间
        
        # 修改二段跳相关属性
        self.can_double_jump = False    # 初始不能二段跳，需要第一次跳跃后才能
        self.is_first_jump = False     # 是否在第一次跳跃的过程中
        
        # 修改地面高度的计算，考虑角色高度
        self.ground_height = self.cfg.physics.ground_height
        self.character_height = self.player_height / 2  # 角色中心点到脚底的距离
        
        # 添加二段跳状态显示
        self.double_jump_text = self.add_double_jump_display()
        
        # 添加跳跃键释放检查
        self.jump_key_released = True  # 跳跃键是否已释放
        self.can_double_jump = False
        self.is_first_jump = False
        
        # 添加下落速度控制
        self.normal_gravity = self.cfg.physics.gravity  # 保存原始重力值
        self.current_gravity = self.normal_gravity      # 当前使用的重力值
        self.is_double_jumping = False                  # 是否在二段跳状态
        
        # 添加二段跳落地相关属性
        self.landing_invincible_start = 0  # 落地无敌开始时间
        self.is_landing_invincible = False  # 是否处于落地无敌状态
        
        # 添加无敌状态光环
        self.create_invincible_halo()
        
    def create_terrain(self):
        # 创建地面
        format = GeomVertexFormat.getV3n3c4()
        vdata = GeomVertexData('square', format, Geom.UHStatic)
        
        vertex = GeomVertexWriter(vdata, 'vertex')
        color = GeomVertexWriter(vdata, 'color')
        
        # 从配置获取地形范围
        x_min, x_max = self.cfg.terrain.size.x
        y_min, y_max = self.cfg.terrain.size.y
        
        # 添加地面顶点
        vertex.addData3(x_min, y_min, -1)
        vertex.addData3(x_max, y_min, -1)
        vertex.addData3(x_max, y_max, -1)
        vertex.addData3(x_min, y_max, -1)
        
        # 添加地面颜色
        for i in range(4):
            color.addData4(*self.cfg.terrain.color)
        
        tris = GeomTriangles(Geom.UHStatic)
        tris.addVertices(0, 1, 2)
        tris.addVertices(0, 2, 3)
        
        geom = Geom(vdata)
        geom.addPrimitive(tris)
        
        node = GeomNode('terrain')
        node.addGeom(geom)
        
        self.terrain = self.render.attachNewNode(node)
        
        # 添加网格线
        self.create_grid()
        
        # 重新启用参考立方体
        self.create_reference_cubes()
        
    def create_grid(self):
        # 创建网格线的顶点数据
        format = GeomVertexFormat.getV3c4()
        vdata = GeomVertexData('grid', format, Geom.UHStatic)
        
        vertex = GeomVertexWriter(vdata, 'vertex')
        color = GeomVertexWriter(vdata, 'color')
        
        # 从配置获取地形范围
        x_min, x_max = self.cfg.terrain.size.x
        y_min, y_max = self.cfg.terrain.size.y
        grid_size = self.cfg.terrain.grid_size
        
        # 计算网格线数量
        num_lines_x = int((x_max - x_min) / grid_size) + 1
        num_lines_y = int((y_max - y_min) / grid_size) + 1
        
        # 创建水平和垂直的网格线
        for i in range(num_lines_x):
            x = x_min + i * grid_size
            # 水平线
            vertex.addData3(x, y_min, -0.9)
            vertex.addData3(x, y_max, -0.9)
            # 添加颜色
            for _ in range(2):
                color.addData4(1, 1, 1, 0.2)
        
        for i in range(num_lines_y):
            y = y_min + i * grid_size
            # 垂直线
            vertex.addData3(x_min, y, -0.9)
            vertex.addData3(x_max, y, -0.9)
            # 添加颜色
            for _ in range(2):
                color.addData4(1, 1, 1, 0.2)
        
        # 创建线段
        lines = GeomLines(Geom.UHStatic)
        for i in range(num_lines_x + num_lines_y):
            lines.addVertices(i * 2, i * 2 + 1)
        
        geom = Geom(vdata)
        geom.addPrimitive(lines)
        
        node = GeomNode('grid')
        node.addGeom(geom)
        
        grid = self.render.attachNewNode(node)
        grid.setTransparency(True)
        
    def create_reference_cubes(self):
        # 从配置中获取布局参数
        cfg = self.cfg.reference_cubes
        x_min, x_max = cfg.layout.x
        y_min, y_max = cfg.layout.y
        spacing = cfg.layout.spacing
        safe_zone = cfg.layout.safe_zone
        
        # 创建参考立方体，避开出生点
        for x in range(x_min, x_max + 1, spacing):
            for y in range(y_min, y_max + 1, spacing):
                # 跳过出生点附近的区域
                if abs(x) < safe_zone and abs(y) < safe_zone:
                    continue
                    
                cube = self.create_cube()
                if cube:
                    # 设置位置和大小
                    cube.setPos(x, y, cfg.appearance.height)
                    cube.setScale(cfg.appearance.scale)
                    
                    # 设置颜色
                    if cfg.appearance.color_variation:
                        # 根据位置设置不同的颜色
                        r = (x - x_min) / (x_max - x_min)
                        b = (y - y_min) / (y_max - y_min)
                        cube.setColor(r, 0.5, b, 1)
                    
                    cube.reparentTo(self.render)
                    
                    # 初始化立方体状态
                    self.cube_states[cube] = {
                        'initial_pos': Point3(x, y, cfg.appearance.height),
                        'velocity': Point3(0, 0, 0),
                        'next_direction_change': random.uniform(0, 2.0),
                        'move_direction': random.uniform(0, 360),
                        'patrol_radius': self.cfg.cube_movement.patrol_radius
                    }
        
    def create_cube(self):
        # 创建立方体的视觉节点
        format = GeomVertexFormat.getV3n3c4()
        vdata = GeomVertexData('cube', format, Geom.UHStatic)
        
        vertex = GeomVertexWriter(vdata, 'vertex')
        normal = GeomVertexWriter(vdata, 'normal')
        color = GeomVertexWriter(vdata, 'color')
        
        # 定义立方体的8个顶点
        points = [
            (-1, -1, -1), (1, -1, -1), (1, 1, -1), (-1, 1, -1),  # 底部
            (-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1)       # 顶部
        ]
        
        # 定义每个面的法线
        normals = [
            (0, 0, -1),  # 底面
            (0, 0, 1),   # 顶面
            (-1, 0, 0),  # 左面
            (1, 0, 0),   # 右面
            (0, -1, 0),  # 前面
            (0, 1, 0),   # 后面
        ]
        
        # 定义面的顶点索引
        faces = [
            (0, 1, 2, 3),  # 底面
            (4, 5, 6, 7),  # 顶面
            (0, 4, 7, 3),  # 左面
            (1, 5, 6, 2),  # 右面
            (0, 1, 5, 4),  # 前面
            (3, 2, 6, 7),  # 后面
        ]
        
        # 添加所有顶点（每个面独立的顶点，以便设置正确的法线）
        for face_i, face in enumerate(faces):
            for vertex_i in face:
                vertex.addData3(*points[vertex_i])
                normal.addData3(*normals[face_i])
                color.addData4(0.5, 0.5, 0.5, 1)  # 灰色
        
        # 创建三角形
        tris = GeomTriangles(Geom.UHStatic)
        for i in range(6):  # 6个面
            base = i * 4    # 每个面4个顶点
            # 每个面由两个三角形组成
            tris.addVertices(base, base + 1, base + 2)
            tris.addVertices(base, base + 2, base + 3)
        
        geom = Geom(vdata)
        geom.addPrimitive(tris)
        
        node = GeomNode('cube')
        node.addGeom(geom)
        
        # 创建立方体的节点路径
        cube = self.render.attachNewNode(node)
        cube.setTwoSided(True)
        
        # 添加碰撞体
        collision_node = CollisionNode('cube_collision')
        collision_box = CollisionBox(Point3(0, 0, 0), 1, 1, 1)
        collision_node.addSolid(collision_box)
        
        # 设置碰撞掩码
        collision_node.setFromCollideMask(BitMask32.bit(1))
        collision_node.setIntoCollideMask(BitMask32.bit(1))
        
        # 将碰撞节点附加到立方体上
        collision_np = cube.attachNewNode(collision_node)
        
        return cube
        
    def setup_mouse(self):
        # 隐藏鼠标光标
        props = WindowProperties()
        props.setCursorHidden(True)
        self.win.requestProperties(props)
        
        # 只需要记录水平移动
        self.last_mouse_x = 0
        
        # 添加鼠标任务
        self.taskMgr.add(self.mouse_task, "MouseTask")
        
    def setup_keyboard(self):
        # 设置键盘控制
        self.keyMap = {
            "forward": False,  # W - 前进
            "backward": False, # S - 后退
            "turn_left": False,  # A - 左转
            "turn_right": False, # D - 右转
            "up": False,      # 空格 - 跳跃
            "down": False     # Shift - 下蹲
        }
        
        # 绑定键盘事件
        self.accept("w", self.update_key, ["forward", True])
        self.accept("w-up", self.update_key, ["forward", False])
        self.accept("s", self.update_key, ["backward", True])
        self.accept("s-up", self.update_key, ["backward", False])
        self.accept("a", self.update_key, ["turn_left", True])
        self.accept("a-up", self.update_key, ["turn_left", False])
        self.accept("d", self.update_key, ["turn_right", True])
        self.accept("d-up", self.update_key, ["turn_right", False])
        self.accept("space", self.update_key, ["up", True])
        self.accept("space-up", self.handle_jump_key_release)  # 添加释放事件处理
        self.accept("lshift", self.update_key, ["down", True])
        self.accept("lshift-up", self.update_key, ["down", False])
        
        # 添加移动任务
        self.taskMgr.add(self.move_task, "MoveTask")
        
        # 添加 ESC 键退出功能
        self.accept("escape", self.quit_game)
        
        # 添加测试用的血量控制键
        self.accept("q", self.update_health, [-10])  # Q键减少血量
        self.accept("e", self.update_health, [10])   # E键恢复血量
        
        # 添加重启游戏快捷键
        self.accept('r', self.restart_game)
        
    def update_key(self, key, value):
        self.keyMap[key] = value
        
    def mouse_task(self, task):
        if self.mouseWatcherNode.hasMouse():
            # 获取鼠标移动
            current_x = self.mouseWatcherNode.getMouseX()
            dx = current_x - self.last_mouse_x
            
            # 更新目标相机角度（相对于角色）
            self.target_camera_heading += -dx * self.mouse_sensitivity
            
            # 限制相机水平旋转范围
            self.target_camera_heading = max(min(self.target_camera_heading, 
                                               90), 
                                               -90)
            
            # 重置鼠标到屏幕中心
            props = self.win.getProperties()
            self.win.movePointer(0, props.getXSize() // 2, props.getYSize() // 2)
            self.last_mouse_x = 0
        
        return Task.cont
        
    def move_task(self, task):
        if not self.game_running:
            return Task.cont
        
        current_time = globalClock.getRealTime()
        dt = globalClock.getDt()
        
        # 检查是否有移动输入
        has_movement = (self.keyMap["forward"] or self.keyMap["backward"] or 
                       self.keyMap["turn_left"] or self.keyMap["turn_right"] or
                       abs(self.velocity.length()) > 0.1)  # 检查是否还在移动
        
        if has_movement:
            self.last_move_time = current_time
        else:
            # 检查是否可以回血
            still_duration = current_time - self.last_move_time
            if (still_duration >= self.cfg.player_status.health_regen.still_time and 
                current_time - self.last_regen_time >= self.cfg.player_status.health_regen.interval):
                # 回血
                if self.health < self.max_health:
                    self.update_health(self.cfg.player_status.health_regen.amount)
                    self.last_regen_time = current_time
        
        dt = globalClock.getDt()
        current_time = task.time
        
        # 处理角色旋转
        turn_speed = 120.0  # 角色旋转速度（度/秒）
        if self.keyMap["turn_left"]:
            self.player_heading += turn_speed * dt
            self.target_camera_heading = 0
        if self.keyMap["turn_right"]:
            self.player_heading -= turn_speed * dt
            self.target_camera_heading = 0
        
        # 平滑插值相机角度到目标角度
        angle_diff = self.target_camera_heading - self.camera_heading
        self.camera_heading += angle_diff * (1 - self.camera_smooth)
        
        # 更新角色朝向
        self.player.setH(self.player_heading)
        
        # 使用角色朝向计算移动方向
        heading_rad = self.player_heading * math.pi / 180.0
        forward = Point3(-math.sin(heading_rad), math.cos(heading_rad), 0)  # 修改正负号
        
        # 计算移动方向（只有前后移动）
        move_direction = Point3(0, 0, 0)
        if self.keyMap["forward"]: move_direction += forward
        if self.keyMap["backward"]: move_direction -= forward
        
        # 处理水平移动
        has_input = move_direction.length() > 0
        if has_input:
            move_direction.normalize()
            horizontal_acceleration = move_direction * self.acceleration * dt
            self.velocity.setX(self.velocity.getX() + horizontal_acceleration.getX())
            self.velocity.setY(self.velocity.getY() + horizontal_acceleration.getY())
            
            # 限制水平速度
            horizontal_speed = math.sqrt(self.velocity.getX()**2 + self.velocity.getY()**2)
            if horizontal_speed > self.max_speed:
                scale = self.max_speed / horizontal_speed
                self.velocity.setX(self.velocity.getX() * scale)
                self.velocity.setY(self.velocity.getY() * scale)
        else:
            self.velocity.setX(self.velocity.getX() * self.deceleration)
            self.velocity.setY(self.velocity.getY() * self.deceleration)
        
        # 计算离地高度
        height_from_ground = self.position.getZ() - (self.ground_height + self.character_height)
        
        # 更新二段跳状态显示
        if (self.is_first_jump and self.can_double_jump and 
            height_from_ground >= self.cfg.physics.double_jump.min_height):
            self.double_jump_text.setText(f'Double Jump Ready! (Cost: {self.cfg.physics.double_jump.health_cost} HP)')
            self.double_jump_text.setFg((0, 1, 0, 1))  # 绿色表示可用
        else:
            if self.is_first_jump and not self.can_double_jump:
                self.double_jump_text.setText('Double Jump Used!')
                self.double_jump_text.setFg((1, 0, 0, 1))  # 红色表示已使用
            else:
                self.double_jump_text.setText('Double Jump Not Ready')
                self.double_jump_text.setFg((0.7, 0.7, 0.7, 1))  # 灰色表示不可用
        
        # 处理落地无敌状态和显示
        if self.is_landing_invincible:
            remaining = self.cfg.physics.double_jump.landing_invincible_time - (current_time - self.landing_invincible_start)
            if remaining > 0:
                # 显示落地无敌状态
                self.invincible_text.setText(f'Landing Invincible: {remaining:.1f}s')
                self.invincible_text.setFg((0, 1, 0, 1))  # 绿色
            else:
                self.is_landing_invincible = False
                self.invincible_text.setText('')
        
        # 修改跳跃冷却检查和显示
        if not self.can_jump:
            # 根据是否是二段跳落地选择不同的冷却时间
            cooldown_time = (self.cfg.physics.double_jump.landing_cooldown 
                            if self.is_double_jumping or 
                            (current_time - self.landing_invincible_start < self.cfg.physics.double_jump.landing_invincible_time)
                            else self.cfg.physics.jump_cooldown)
            
            remaining = cooldown_time - (current_time - self.last_jump_time)
            if remaining <= 0:
                self.can_jump = True
                self.jump_cooldown_text.setText('Jump Ready')
                self.jump_cooldown_text.setFg((1, 1, 1, 1))
            else:
                self.jump_cooldown_text.setText(f'Jump Cooldown: {remaining:.1f}s')
                # 使用不同颜色区分普通冷却和二段跳冷却
                self.jump_cooldown_text.setFg((1, 0, 0, 1) if cooldown_time > self.cfg.physics.jump_cooldown 
                                            else (1, 0.5, 0, 1))
        
        # 处理跳跃
        if self.keyMap["up"]:
            current_time = globalClock.getRealTime()
            
            # 如果在无敌状态下，不允许跳跃
            if not self.is_invincible and not self.is_landing_invincible:
                # 在地面上时可以进行普通跳跃
                if self.position.getZ() <= self.ground_height + self.character_height + 0.1:
                    if self.can_jump:  # 检查是否可以跳跃
                        self.velocity.setZ(self.jump_speed)
                        self.last_jump_time = current_time
                        self.can_jump = False  # 进入冷却
                        self.is_first_jump = True
                        self.can_double_jump = True
                        self.jump_key_released = False
                
                # 在空中且达到最小高度时才能二段跳
                elif (self.is_first_jump and self.can_double_jump and 
                      height_from_ground >= self.cfg.physics.double_jump.min_height and
                      self.jump_key_released):
                    # 检查血量是否足够
                    if self.health > self.cfg.physics.double_jump.health_cost:
                        # 计算达到指定高度所需的初速度
                        # 使用运动学公式：v = sqrt(2gh)，其中g是重力加速度，h是目标高度
                        target_height = self.cfg.physics.double_jump.height
                        jump_speed = math.sqrt(2 * abs(self.gravity) * target_height)
                        
                        self.velocity.setZ(jump_speed)  # 使用计算出的速度
                        self.can_double_jump = False
                        self.jump_key_released = False
                        # 扣除血量
                        self.update_health(-self.cfg.physics.double_jump.health_cost)
                        # 显示二段跳已使用状态
                        self.double_jump_text.setText('Double Jump Used!')
                        self.double_jump_text.setFg((1, 0, 0, 1))
                        
                        self.is_double_jumping = True  # 标记进入二段跳状态
                        # 调整重力
                        self.current_gravity = self.normal_gravity * self.cfg.physics.double_jump.fall_speed_scale
        
        # 应用当前重力（而不是直接使用 self.gravity）
        self.velocity.setZ(self.velocity.getZ() + self.current_gravity * dt)
        
        # 更新位置
        self.position += self.velocity * dt
        
        # 落地检测
        if self.position.getZ() <= self.ground_height + self.character_height:
            self.position.setZ(self.ground_height + self.character_height)
            self.velocity.setZ(0)
            self.is_first_jump = False
            self.can_double_jump = False
            
            # 如果是从二段跳落地
            if self.is_double_jumping:
                current_time = globalClock.getRealTime()
                # 设置落地无敌
                self.is_landing_invincible = True
                self.landing_invincible_start = current_time
                # 设置更长的跳跃冷却
                self.last_jump_time = current_time
                self.can_jump = False
                # 重置重力
                self.current_gravity = self.normal_gravity
                self.is_double_jumping = False
        
        # 处理落地无敌状态
        if self.is_landing_invincible:
            if current_time - self.landing_invincible_start >= self.cfg.physics.double_jump.landing_invincible_time:
                self.is_landing_invincible = False
        
        # 更新角色位置
        self.player.setPos(self.position)
        
        # 进行碰撞检测
        self.cTrav.traverse(self.render)
        
        # 检查碰撞队列
        if self.collision_queue.getNumEntries() > 0:
            self.handle_cube_collision(None)
        
        # 如果发生碰撞，position需要更新为实际位置
        self.position = self.player.getPos()
        
        # 更新相机位置
        self.update_camera()
        
        # 更新显示信息
        x = round(self.position.getX(), 2)
        y = round(self.position.getY(), 2)
        z = round(self.position.getZ(), 2)
        speed = round(self.velocity.length(), 2)
        
        # 获取相机信息
        cam_pos = self.camera.getPos()
        cam_hpr = self.camera.getHpr()
        
        # 更新显示文本
        self.pos_text.setText(
            f'Player Position: ({x}, {y}, {z})\n'
            f'Player Heading: {round(self.player_heading, 2)}°\n'
            f'Player Speed: {speed}\n'
            f'Player Velocity: ({round(self.velocity.getX(), 2)}, '
            f'{round(self.velocity.getY(), 2)}, '
            f'{round(self.velocity.getZ(), 2)})\n'
            f'Camera Position: ({round(cam_pos.getX(), 2)}, '
            f'{round(cam_pos.getY(), 2)}, '
            f'{round(cam_pos.getZ(), 2)})\n'
            f'Camera HPR: ({round(cam_hpr.getX(), 2)}, '
            f'{round(cam_hpr.getY(), 2)}, '
            f'{round(cam_hpr.getZ(), 2)})'
        )
        
        # 更新得分显示（存活时间）
        if self.game_running:
            survival_time = int(globalClock.getRealTime() - self.start_time)
            self.score_text.setText(f'Survival Time: {survival_time}s')
        
        # 更新无敌状态
        current_time = globalClock.getRealTime()
        if self.is_invincible:
            remaining = self.invincible_end_time - current_time
            if remaining > 0:
                self.invincible_text.setText(f'Invincible: {remaining:.1f}s')
                # 让角色闪烁以显示无敌状态
                self.player.setAlphaScale(0.5 + 0.5 * math.sin(current_time * 10))
            else:
                self.is_invincible = False
                self.invincible_text.setText('')
                self.player.setAlphaScale(1.0)  # 恢复正常显示
        elif current_time - self.last_damage_time < self.damage_cooldown:
            # 显示伤害冷却时间
            remaining = self.damage_cooldown - (current_time - self.last_damage_time)
            self.invincible_text.setText(f'Damage Cooldown: {remaining:.1f}s')
            # 让角色轻微闪烁表示在冷却中
            self.player.setAlphaScale(0.7 + 0.3 * math.sin(current_time * 5))
        else:
            self.invincible_text.setText('')
            self.player.setAlphaScale(1.0)
        
        # 检查是否超出边界
        self.check_boundaries()
        
        # 更新无敌状态效果
        self.update_invincible_state()
        
        return Task.cont

    def add_position_display(self):
        # 创建屏幕文本，调整位置和大小
        pos_text = OnscreenText(
            text='Initializing...',
            pos=(-1.3, 0.9),     # 左上角位置
            scale=0.05,          # 稍微调小字体
            fg=(1, 1, 1, 1),     # 白色文本
            align=TextNode.ALeft, # 左对齐
            mayChange=True)      # 允许更新文本
        return pos_text

    def create_player(self):
        # 创建纵向长方体
        format = GeomVertexFormat.getV3n3c4()
        vdata = GeomVertexData('player', format, Geom.UHStatic)
        
        vertex = GeomVertexWriter(vdata, 'vertex')
        normal = GeomVertexWriter(vdata, 'normal')
        color = GeomVertexWriter(vdata, 'color')
        
        # 定义长方体的8个顶点
        h = self.player_height / 2
        w = self.player_width / 2
        d = self.player_depth / 2
        points = [
            (-w, -d, -h), (w, -d, -h), (w, d, -h), (-w, d, -h),  # 底部
            (-w, -d, h), (w, -d, h), (w, d, h), (-w, d, h)       # 顶部
        ]
        
        # 定义每个面的法线
        normals = [
            (0, 0, -1),  # 底面
            (0, 0, 1),   # 顶面
            (-1, 0, 0),  # 左面
            (1, 0, 0),   # 右面
            (0, -1, 0),  # 前面
            (0, 1, 0),   # 后面
        ]
        
        # 定义面的顶点索引
        faces = [
            (0, 1, 2, 3),  # 底面
            (4, 5, 6, 7),  # 顶面
            (0, 4, 7, 3),  # 左面
            (1, 5, 6, 2),  # 右面
            (0, 1, 5, 4),  # 前面
            (3, 2, 6, 7),  # 后面
        ]
        
        # 添加所有顶点（每个顶点重复添加，以便设置不同的法线）
        for face_i, face in enumerate(faces):
            for vertex_i in face:
                vertex.addData3(*points[vertex_i])
                normal.addData3(*normals[face_i])
                color.addData4(0.2, 0.5, 0.8, 1)  # 蓝色
        
        # 创建三角形
        tris = GeomTriangles(Geom.UHStatic)
        for i in range(6):  # 6个面
            base = i * 4    # 每个面4个顶点
            # 每个面由两个三角形组成
            tris.addVertices(base, base + 1, base + 2)
            tris.addVertices(base, base + 2, base + 3)
        
        geom = Geom(vdata)
        geom.addPrimitive(tris)
        
        node = GeomNode('player')
        node.addGeom(geom)
        
        # 创建并返回节点
        player = self.render.attachNewNode(node)
        player.setTwoSided(True)  # 允许双面显示
        
        # 添加方向指示器（小方块）
        self.direction_indicator = self.create_direction_indicator()
        self.direction_indicator.reparentTo(player)
        # 将小方块放在角色前方
        self.direction_indicator.setPos(0, self.player_depth + 0.3, 0)
        
        return player

    def create_direction_indicator(self):
        # 创建一个小方块作为方向指示器
        format = GeomVertexFormat.getV3n3c4()
        vdata = GeomVertexData('direction_indicator', format, Geom.UHStatic)
        
        vertex = GeomVertexWriter(vdata, 'vertex')
        normal = GeomVertexWriter(vdata, 'normal')
        color = GeomVertexWriter(vdata, 'color')
        
        # 定义小方块的尺寸
        size = 0.3  # 小方块的大小
        points = [
            (-size, -size, -size), (size, -size, -size), (size, size, -size), (-size, size, -size),  # 底部
            (-size, -size, size), (size, -size, size), (size, size, size), (-size, size, size)       # 顶部
        ]
        
        # 使用与create_cube相同的法线和面定义
        normals = [
            (0, 0, -1),  # 底面
            (0, 0, 1),   # 顶面
            (-1, 0, 0),  # 左面
            (1, 0, 0),   # 右面
            (0, -1, 0),  # 前面
            (0, 1, 0),   # 后面
        ]
        
        faces = [
            (0, 1, 2, 3),  # 底面
            (4, 5, 6, 7),  # 顶面
            (0, 4, 7, 3),  # 左面
            (1, 5, 6, 2),  # 右面
            (0, 1, 5, 4),  # 前面
            (3, 2, 6, 7),  # 后面
        ]
        
        # 添加所有顶点
        for face_i, face in enumerate(faces):
            for vertex_i in face:
                vertex.addData3(*points[vertex_i])
                normal.addData3(*normals[face_i])
                color.addData4(1, 0, 0, 1)  # 红色，使其更显眼
        
        # 创建三角形
        tris = GeomTriangles(Geom.UHStatic)
        for i in range(6):
            base = i * 4
            tris.addVertices(base, base + 1, base + 2)
            tris.addVertices(base, base + 2, base + 3)
        
        geom = Geom(vdata)
        geom.addPrimitive(tris)
        
        node = GeomNode('direction_indicator')
        node.addGeom(geom)
        
        indicator = NodePath(node)
        indicator.setTwoSided(True)
        
        return indicator

    def update_camera(self):
        # 计算相机的目标位置（在角色正后方固定距离）
        total_heading_rad = (self.player_heading + self.camera_heading + 180) * math.pi / 180.0
        pitch_rad = self.camera_pitch * math.pi / 180.0
        
        # 计算相机在水平面上的偏移
        offset_x = math.sin(-total_heading_rad) * self.camera_distance
        offset_y = math.cos(-total_heading_rad) * self.camera_distance
        
        # 计算相机的垂直偏移（考虑俯视角度）
        height_offset = -math.sin(pitch_rad) * self.camera_distance
        vertical_distance = math.cos(pitch_rad) * self.camera_distance
        
        # 计算最终的目标位置
        target_x = self.position.getX() + offset_x
        target_y = self.position.getY() + offset_y
        target_z = self.position.getZ() + self.camera_height + height_offset
        
        # 设置相机位置
        self.camera.setPos(target_x, target_y, target_z)
        
        # 让相机看向角色的上半身位置
        look_height = self.player_height * 0.75
        self.camera.lookAt(
            self.position.getX(),
            self.position.getY(),
            self.position.getZ() + look_height
        )
        
        # 固定相机的上方向
        self.camera.setR(0)

    def setup_player_collision(self):
        # 创建角色的碰撞体
        collision_node = CollisionNode('player')
        collision_capsule = CollisionCapsule(
            Point3(0, 0, -self.player_height/2),
            Point3(0, 0, self.player_height/2),
            self.player_width/2
        )
        collision_node.addSolid(collision_capsule)
        
        # 设置碰撞掩码
        collision_node.setFromCollideMask(BitMask32.bit(1))
        collision_node.setIntoCollideMask(BitMask32.bit(1))
        
        # 将碰撞节点附加到角色上
        self.player_collision = self.player.attachNewNode(collision_node)
        
        # 添加到碰撞系统，使用队列处理器
        self.cTrav.addCollider(self.player_collision, self.collision_queue)
        
        # 添加碰撞事件处理
        self.accept('into-player', self.handle_cube_collision)

    def handle_cube_collision(self, entry):
        if self.game_running:
            current_time = globalClock.getRealTime()
            # 检查是否在无敌时间内（包括落地无敌）
            if not self.is_invincible and not self.is_landing_invincible:
                # 检查是否在伤害冷却时间内
                if current_time - self.last_damage_time >= self.damage_cooldown:
                    self.update_health(-self.cfg.game_rules.damage.cube_collision)
                    self.last_damage_time = current_time
                    # 受伤时闪烁效果
                    self.player.setColor(1, 0, 0, 1)  # 变红
                    taskMgr.doMethodLater(0.1, self.reset_player_color, 'ResetPlayerColor')
                    if self.health <= 0:
                        self.game_over()

    def reset_player_color(self, task):
        self.player.setColor(0.2, 0.5, 0.8, 1)  # 恢复原来的蓝色
        return Task.done

    def game_over(self):
        self.game_running = False
        
        # 计算最终得分（存活时间）
        self.survival_time = int(globalClock.getRealTime() - self.start_time)
        
        # 如果已经存在游戏结束文本，先移除它
        if hasattr(self, 'game_over_text') and self.game_over_text:
            self.game_over_text.destroy()
        
        # 创建新的游戏结束文本
        self.game_over_text = OnscreenText(
            text=f'Game Over!\nSurvival Time: {self.survival_time} seconds\n\nPress R to restart',
            pos=tuple(self.cfg.game_rules.game_over.text_position),
            scale=self.cfg.game_rules.game_over.text_scale,
            fg=(1, 0, 0, 1),
            align=TextNode.ACenter,
            mayChange=True
        )

    def restart_game(self):
        # 移除游戏结束文本
        if hasattr(self, 'game_over_text') and self.game_over_text:
            self.game_over_text.destroy()
            delattr(self, 'game_over_text')  # 完全移除属性
        
        # 重置玩家状态
        self.health = self.cfg.player_status.initial_health
        self.update_health(0)  # 更新血条显示
        
        # 重置位置
        self.position = Point3(*self.cfg.player.initial_position)
        self.velocity = Point3(0, 0, 0)
        self.player.setPos(self.position)
        
        # 重置游戏状态
        self.game_running = True
        self.start_time = globalClock.getRealTime()
        
        # 重新开始无敌时间
        self.start_invincible_time()
        self.player.setAlphaScale(1.0)  # 确保透明度重置
        
        # 重置所有边界相关状态
        self.boundary_violations = []
        self.last_boundary_return_time = 0
        self.warning_active = False
        self.warning_start_time = 0
        if hasattr(self, 'warning_text') and self.warning_text:
            self.warning_text.destroy()  # 同样使用 destroy
            self.warning_text = None
        
        # 重置边界返回文本
        self.boundary_return_text.setText('')
        self.boundary_return_text.setFg((1, 1, 1, 1))  # 重置颜色为白色
        
        # 移除任何正在运行的警告任务
        taskMgr.remove("BlinkWarning")
        
        # 重置二段跳状态显示
        self.double_jump_text.setText('Double Jump Not Ready')
        self.double_jump_text.setFg((0.7, 0.7, 0.7, 1))
        
        # 重置跳跃相关状态
        self.jump_key_released = True
        self.can_double_jump = False
        self.is_first_jump = False
        
        # 重置重力相关状态
        self.current_gravity = self.normal_gravity
        self.is_double_jumping = False
        
        # 重置落地无敌状态
        self.is_landing_invincible = False
        self.landing_invincible_start = 0
        
        # 重置光环效果
        self.invincible_halo.setH(0)
        self.invincible_halo.setScale(1)
        self.invincible_halo.setColorScale(1, 0.8, 0, 0.5)

    def update_cubes_task(self, task):
        if not self.game_running:
            return Task.cont
        
        dt = globalClock.getDt()
        current_time = task.time
        
        for cube, state in self.cube_states.items():
            # 更新方向
            if current_time >= state['next_direction_change']:
                # 计算当前位置到初始位置的距离
                current_pos = cube.getPos()
                to_initial = state['initial_pos'] - current_pos
                dist_to_initial = to_initial.length()
                
                if dist_to_initial > state['patrol_radius']:
                    # 如果超出巡逻范围，直接朝向初始位置移动
                    angle_to_initial = math.atan2(to_initial.getY(), to_initial.getX())
                    state['move_direction'] = math.degrees(angle_to_initial)
                    # 当需要返回时增加速度
                    move_speed = self.cfg.cube_movement.base_speed * 1.5
                else:
                    # 在范围内随机移动
                    state['move_direction'] = random.uniform(0, 360)
                    move_speed = self.cfg.cube_movement.base_speed
                
                # 设置下一次改变方向的时间
                state['next_direction_change'] = current_time + random.uniform(
                    self.cfg.cube_movement.direction_change.min_interval,
                    self.cfg.cube_movement.direction_change.max_interval
                )
            else:
                move_speed = self.cfg.cube_movement.base_speed
            
            # 计算移动方向
            direction_rad = math.radians(state['move_direction'])
            
            # 更新速度
            state['velocity'].setX(math.cos(direction_rad) * move_speed)
            state['velocity'].setY(math.sin(direction_rad) * move_speed)
            
            # 更新位置
            pos = cube.getPos()
            new_pos = pos + state['velocity'] * dt
            
            # 保持高度不变
            new_pos.setZ(1)
            
            # 更新立方体位置
            cube.setPos(new_pos)
            
            # 添加旋转
            rotation_speed = random.uniform(
                self.cfg.cube_movement.rotation_speed[0],
                self.cfg.cube_movement.rotation_speed[1]
            )
            cube.setH(cube.getH() + rotation_speed)
        
        return Task.cont

    def add_jump_cooldown_display(self):
        # 创建跳跃冷却显示文本
        cooldown_text = OnscreenText(
            text='Jump Ready',
            pos=(-1.3, 0.5),     # 位置在左侧中部
            scale=0.05,
            fg=(1, 1, 1, 1),
            align=TextNode.ALeft,
            mayChange=True
        )
        return cooldown_text

    def add_score_display(self):
        # 创建得分显示文本
        score_text = OnscreenText(
            text='Survival Time: 0s',
            pos=tuple(self.cfg.game_rules.score.position),
            scale=self.cfg.game_rules.score.scale,
            fg=(1, 1, 1, 1),
            align=TextNode.ARight,
            mayChange=True
        )
        return score_text

    def add_invincible_display(self):
        # 创建无敌时间显示文本
        invincible_text = OnscreenText(
            text='',
            pos=(-0.25, 0.8),  # 位置在血条下方
            scale=0.05,
            fg=(1, 1, 0, 1),  # 黄色
            align=TextNode.ALeft,
            mayChange=True
        )
        return invincible_text

    def start_invincible_time(self):
        self.is_invincible = True
        current_time = globalClock.getRealTime()
        self.invincible_end_time = current_time + self.cfg.game_rules.damage.invincible_time

    def quit_game(self):
        # 退出游戏
        self.userExit()

    def setup_health_bar(self):
        # 创建血条标签
        self.health_text = OnscreenText(
            text='Health',
            pos=(self.cfg.player_status.health_bar.position[0],
                 self.cfg.player_status.health_bar.position[1] + 0.05),
            scale=0.05,
            fg=(1, 1, 1, 1),
            align=TextNode.ALeft,
            mayChange=True
        )
        
        # 创建血条
        self.health_bar = DirectWaitBar(
            text="",
            value=self.health,
            range=self.max_health,
            pos=(self.cfg.player_status.health_bar.position[0] + 
                 self.cfg.player_status.health_bar.width/2,
                 0,
                 self.cfg.player_status.health_bar.position[1]),
            barColor=tuple(self.cfg.player_status.health_bar.colors.fill),
            frameColor=tuple(self.cfg.player_status.health_bar.colors.background),
            scale=(self.cfg.player_status.health_bar.width,
                  1,
                  self.cfg.player_status.health_bar.height)
        )
        
        # 添加血量数值显示
        self.health_value_text = OnscreenText(
            text=f'{self.health}/{self.max_health}',
            pos=(self.cfg.player_status.health_bar.position[0] + 
                 self.cfg.player_status.health_bar.width + 0.05,
                 self.cfg.player_status.health_bar.position[1]),
            scale=0.05,
            fg=(1, 1, 1, 1),
            align=TextNode.ALeft,
            mayChange=True
        )
        
        # 立即更新血条颜色
        self.update_health(0)  # 调用update_health来设置正确的颜色

    def update_health(self, amount):
        """更新生命值"""
        self.health = max(0, min(self.max_health, self.health + amount))
        self.health_bar['value'] = self.health
        self.health_value_text.setText(f'{int(self.health)}/{self.max_health}')
        
        # 根据血量改变血条颜色
        if self.health > self.max_health * 0.7:  # 血量 > 70%
            self.health_bar['barColor'] = (0.2, 0.8, 0.2, 1.0)  # 绿色
        elif self.health > self.max_health * 0.3:  # 血量 > 30%
            self.health_bar['barColor'] = (0.8, 0.8, 0.2, 1.0)  # 黄色
        else:  # 血量 <= 30%
            self.health_bar['barColor'] = (0.8, 0.2, 0.2, 1.0)  # 红色
        
        # 检查是否血量归零
        if self.health <= 0 and self.game_running:
            self.game_over()

    def check_boundaries(self):
        current_time = globalClock.getRealTime()
        pos_x = self.position.getX()
        pos_y = self.position.getY()
        
        # 检查是否超出边界
        x_min, x_max = self.cfg.game_rules.boundaries.x
        y_min, y_max = self.cfg.game_rules.boundaries.y
        
        if (pos_x < x_min or pos_x > x_max or 
            pos_y < y_min or pos_y > y_max):
            if not self.warning_active:
                # 开始警告
                self.warning_active = True
                self.warning_start_time = current_time
                
                # 检查是否在安全返回时间内
                if self.last_boundary_return_time > 0:
                    time_since_return = current_time - self.last_boundary_return_time
                    if time_since_return < self.cfg.game_rules.boundaries.violation.safe_return_time:
                        # 如果在安全返回时间内再次离开边界，直接游戏结束
                        print(f"Game Over! Left boundary too soon (after {time_since_return:.1f}s)")
                        self.update_health(-self.max_health)  # 直接扣除所有血量
                        return
                
                self.show_warning()
            else:
                # 检查警告时间是否结束
                if current_time - self.warning_start_time >= self.cfg.game_rules.damage.warning_time:
                    # 记录违规时间并清理过期记录
                    self.boundary_violations.append(current_time)
                    time_window = self.cfg.game_rules.boundaries.violation.count_time
                    self.boundary_violations = [t for t in self.boundary_violations 
                                             if current_time - t <= time_window]
                    
                    # 检查违规次数
                    if len(self.boundary_violations) >= self.cfg.game_rules.boundaries.violation.max_violations:
                        # 两次违规，造成双倍伤害
                        self.update_health(-self.cfg.game_rules.damage.out_of_bounds * 2)
                        # 清空违规记录
                        self.boundary_violations = []
                        print("Double damage applied! Violations reset.")  # 调试信息
                    else:
                        # 正常的边界伤害
                        self.update_health(-self.cfg.game_rules.damage.out_of_bounds)
                        print(f"Normal damage applied. Violations: {len(self.boundary_violations)}")  # 调试信息
                    
                    # 重置警告状态
                    self.reset_warning()
        else:
            # 如果回到边界内，记录返回时间
            if self.warning_active:
                self.last_boundary_return_time = current_time
                self.reset_warning()
        
        # 更新返回时间显示
        if self.last_boundary_return_time > 0:
            time_since_return = current_time - self.last_boundary_return_time
            safe_time = self.cfg.game_rules.boundaries.violation.safe_return_time
            if time_since_return < safe_time:
                remaining = safe_time - time_since_return
                self.boundary_return_text.setText(
                    f'Safe Return Time: {remaining:.1f}s'
                )
                # 使用红色表示危险期
                self.boundary_return_text.setFg((1, 0, 0, 1))
            else:
                self.boundary_return_text.setText(
                    f'Last Return: {time_since_return:.1f}s ago'
                )
                # 使用绿色表示安全期
                self.boundary_return_text.setFg((0, 1, 0, 1))

    def show_warning(self):
        # 创建警告文本
        self.warning_text = OnscreenText(
            text="!",
            pos=(0, 0.2),  # 在屏幕中上方
            scale=self.cfg.game_rules.warning.text_scale,
            fg=tuple(self.cfg.game_rules.warning.text_color),
            align=TextNode.ACenter,
            mayChange=True
        )
        
        # 添加闪烁效果任务
        taskMgr.add(self.blink_warning, "BlinkWarning")

    def reset_warning(self):
        self.warning_active = False
        if self.warning_text:
            self.warning_text.destroy()
            self.warning_text = None
        taskMgr.remove("BlinkWarning")

    def blink_warning(self, task):
        if not self.warning_active or not self.warning_text:
            return Task.done
        
        current_time = globalClock.getRealTime()
        # 计算剩余警告时间
        remaining = self.cfg.game_rules.damage.warning_time - (current_time - self.warning_start_time)
        
        if remaining <= 0:
            return Task.done
        
        # 闪烁效果 - 使用setFg来设置颜色和透明度
        alpha = 0.5 + 0.5 * math.sin(current_time * 5)
        color = self.cfg.game_rules.warning.text_color
        self.warning_text.setFg((color[0], color[1], color[2], alpha))
        
        # 更新警告文本
        self.warning_text.setText(f"!\n{remaining:.1f}s")
        
        return Task.cont

    def add_boundary_return_display(self):
        # 创建边界返回时间显示文本
        return_text = OnscreenText(
            text='',
            pos=(-1.3, 0.3),     # 位置在左侧信息区域
            scale=0.05,
            fg=(1, 1, 1, 1),
            align=TextNode.ALeft,
            mayChange=True
        )
        return return_text

    def add_double_jump_display(self):
        # 创建二段跳状态显示文本
        double_jump_text = OnscreenText(
            text='',
            pos=(-1.3, 0.4),     # 位置在左侧信息区
            scale=0.05,
            fg=(1, 1, 1, 1),
            align=TextNode.ALeft,
            mayChange=True
        )
        return double_jump_text

    def handle_jump_key_release(self):
        self.keyMap["up"] = False
        self.jump_key_released = True  # 标记跳跃键已释放

    def create_invincible_halo(self):
        # 创建光环的顶点数据
        format = GeomVertexFormat.getV3c4()
        vdata = GeomVertexData('halo', format, Geom.UHStatic)
        
        vertex = GeomVertexWriter(vdata, 'vertex')
        color = GeomVertexWriter(vdata, 'color')
        
        # 创建一个圆形光环
        segments = 32  # 圆的分段数
        radius = 2.0   # 光环半径
        thickness = 0.2  # 光环厚度
        
        # 创建内圈和外圈的顶点
        for i in range(segments + 1):
            angle = 2.0 * math.pi * i / segments
            x = math.cos(angle)
            y = math.sin(angle)
            
            # 内圈顶点
            vertex.addData3(x * (radius - thickness), y * (radius - thickness), 0.1)
            # 外圈顶点
            vertex.addData3(x * radius, y * radius, 0.1)
            
            # 添加颜色（黄色半透明）
            color.addData4(1, 1, 0, 0.5)  # 内圈颜色
            color.addData4(1, 1, 0, 0)    # 外圈颜色（渐变到透明）
        
        # 创建三角形带
        tris = GeomTristrips(Geom.UHStatic)
        for i in range(segments * 2 + 2):
            tris.addVertex(i)
        
        geom = Geom(vdata)
        geom.addPrimitive(tris)
        
        node = GeomNode('invincible_halo')
        node.addGeom(geom)
        
        # 创建光环节点
        self.invincible_halo = self.player.attachNewNode(node)
        self.invincible_halo.setTwoSided(True)  # 双面显示
        self.invincible_halo.setTransparency(True)  # 启用透明度
        self.invincible_halo.setP(90)  # 使光环水平
        self.invincible_halo.hide()  # 初始时隐藏

    def update_invincible_state(self):
        current_time = globalClock.getRealTime()
        
        if self.is_invincible or self.is_landing_invincible:
            # 显示光环并更新效果
            self.invincible_halo.show()
            
            # 旋转光环
            rotation_speed = 90  # 每秒旋转90度
            self.invincible_halo.setH((current_time * rotation_speed) % 360)
            
            # 缩放呼吸效果
            scale = 1.0 + 0.1 * math.sin(current_time * 5)
            self.invincible_halo.setScale(scale)
            
            # 更新颜色
            if self.is_invincible:
                # 出生无敌时为金色
                self.invincible_halo.setColorScale(1, 0.8, 0, 0.5 + 0.2 * math.sin(current_time * 5))
            else:
                # 落地无敌时为蓝色
                self.invincible_halo.setColorScale(0, 0.8, 1, 0.5 + 0.2 * math.sin(current_time * 5))
        else:
            # 隐藏光环
            self.invincible_halo.hide()

game = SandboxGame()
game.run() 