from flask import Flask, Response, request, render_template
import Box2D
from Box2D.b2 import (world, polygonShape, staticBody, dynamicBody, fixtureDef)
import time
import random
import math
import json
from threading import Lock

app = Flask(__name__)

# Масштабирование Box2D мира (1 единица = 1 пиксель)
PPM = 1.0

class GameState:
    def __init__(self):
        self.lock = Lock()
        self.reset()

    def reset(self):
        with self.lock:
            # Создаем Box2D мир с гравитацией (0, 0)
            self.world = world(gravity=(0, 0))
            self.input_state = {"left": False, "right": False, "forward": False}
            self.bodies = {}
            self.bot_info = {}
            
            # Создаем границы мира
            self._create_walls()
            
            # Создаем машины
            for i in range(10):
                self._create_car(f"car_{i}", random.uniform(100, 700), random.uniform(100, 500))
            
            self.player_id = "car_0"
            self.player_body = self.bodies[self.player_id]
            
            # Создаем препятствия
            self.obstacles = []
            self._create_obstacles(20)

    def _create_walls(self):
        wall_def = fixtureDef(shape=polygonShape(box=(400, 10)), restitution=0.1)
        
        # Нижняя стена
        wall = self.world.CreateStaticBody(position=(400, -10))
        wall.CreateFixture(fixtureDef(shape=polygonShape(box=(400, 10)), restitution=0.1))
        
        # Верхняя стена
        wall = self.world.CreateStaticBody(position=(400, 610))
        wall.CreateFixture(fixtureDef(shape=polygonShape(box=(400, 10)), restitution=0.1))
        
        # Левая стена
        wall = self.world.CreateStaticBody(position=(-10, 300))
        wall.CreateFixture(fixtureDef(shape=polygonShape(box=(10, 300)), restitution=0.1))
        
        # Правая стена
        wall = self.world.CreateStaticBody(position=(810, 300))
        wall.CreateFixture(fixtureDef(shape=polygonShape(box=(10, 300)), restitution=0.1))

    def _create_car(self, car_id, x, y):
        body = self.world.CreateDynamicBody(position=(x, y))
        box = body.CreatePolygonFixture(box=(20, 10), density=1, friction=0.3, restitution=0.2)
        self.bodies[car_id] = body
        self.bot_info[car_id] = {"last_switch": time.time(), "chasing": False}

    def _create_obstacles(self, count):
        for _ in range(count):
            kind = random.choice(["square", "triangle"])
            x, y = random.uniform(100, 700), random.uniform(100, 500)
            s = random.uniform(20, 60)
            
            if kind == "square":
                body = self.world.CreateStaticBody(position=(x + s/2, y + s/2))
                body.CreatePolygonFixture(box=(s/2, s/2), restitution=0.1)
                self.obstacles.append(("square", x, y, s))
            else:
                body = self.world.CreateStaticBody(position=(x + s/2, y))
                vertices = [(0, 0), (s, 0), (s/2, -s)]
                body.CreatePolygonFixture(vertices=vertices, restitution=0.1)
                self.obstacles.append(("triangle", x, y, s))

    def step(self, dt):
        with self.lock:
            # Управление игроком
            player_body = self.bodies[self.player_id]
            
            # Поворот
            if self.input_state["left"]:
                player_body.angularVelocity = -2.5
            elif self.input_state["right"]:
                player_body.angularVelocity = 2.5
            else:
                player_body.angularVelocity *= 0.8  # Плавная остановка вращения
            
            # Движение вперед
            if self.input_state["forward"]:
                # Получаем текущий угол поворота машины
                angle = player_body.angle
                # Вычисляем вектор силы (вперед относительно машины)
                force_magnitude = 400000
                force_x = math.cos(angle) * force_magnitude
                force_y = math.sin(angle) * force_magnitude
                # Применяем силу в центре масс
                player_body.ApplyForce(force=(force_x, force_y), point=player_body.worldCenter, wake=True)
            else:
                # Линейное демпфирование для плавной остановки
                player_body.linearVelocity *= 0.98

            # ИИ ботов
            now = time.time()
            for cid, body in self.bodies.items():
                if cid == self.player_id:
                    continue
                
                info = self.bot_info[cid]
                if now - info["last_switch"] > 5:
                    info["last_switch"] = now
                    info["chasing"] = random.random() < 0.5
                
                if info["chasing"]:
                    # Преследование игрока
                    dx = self.player_body.position.x - body.position.x
                    dy = self.player_body.position.y - body.position.y
                    desired_angle = math.atan2(dy, dx)
                    angle_diff = (desired_angle - body.angle + math.pi) % (2 * math.pi) - math.pi
                    body.angularVelocity = angle_diff * 5
                else:
                    # Случайное блуждание
                    if random.random() < 0.02:
                        body.angularVelocity = random.uniform(-2, 2)
                    else:
                        body.angularVelocity *= 0.95
                
                # Всегда двигаемся вперед
                angle = body.angle
                force_x = math.cos(angle) * 200
                force_y = math.sin(angle) * 200
                body.ApplyForce(force=(force_x, force_y), point=body.worldCenter, wake=True)

            # Шаг физики
            self.world.Step(dt, velocityIterations=6, positionIterations=2)
            self.world.ClearForces()

    def snapshot(self):
        with self.lock:
            cars = []
            for cid, body in self.bodies.items():
                cars.append({
                    "id": cid,
                    "x": body.position.x,
                    "y": body.position.y,
                    "w": 40,
                    "h": 20,
                    "angle": body.angle
                })
            return {"cars": cars, "obstacles": self.obstacles, "player": self.player_id}

game = GameState()

def event_stream():
    last = time.time()
    while True:
        now = time.time()
        dt = now - last
        last = now
        game.step(dt)
        yield f"data: {json.dumps(game.snapshot())}\n\n"
        time.sleep(1/60)

@app.route("/stream")
def stream():
    return Response(event_stream(), mimetype="text/event-stream")

@app.route("/input", methods=["POST"])
def set_input():
    data = request.get_json()
    with game.lock:
        for k in ("left", "right", "forward"):
            if k in data:
                game.input_state[k] = bool(data[k])
    return ("", 204)

@app.route("/restart", methods=["POST"])
def restart():
    game.reset()
    return ("", 204)

@app.route("/")
def index():
    return render_template("index.html")

if __name__ == "__main__":
    app.run(debug=True, threaded=True)