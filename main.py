from fastapi import FastAPI, Request, Form, HTTPException, Cookie
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import aiosqlite
import aiohttp
from datetime import datetime
from passlib.context import CryptContext
from jose import JWTError, jwt
import secrets
from typing import Optional
from jinja2 import Template
import logging
import os
import base64
from pathlib import Path
from fastapi.templating import Jinja2Templates

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 应用配置
app = FastAPI()
SECRET_KEY = secrets.token_urlsafe(32)
FIXER_API_KEY = os.getenv("FIXER_API_KEY")
DB_PATH = os.path.join('data', 'vps.db')

# 确保数据目录存在
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

# 密码处理
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# 设置模板目录
templates = Jinja2Templates(directory="templates")

# HTML模板直接嵌入到代码中
HTML_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>VPS Value Tracker</title>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css" rel="stylesheet">
    <link href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.7.2/font/bootstrap-icons.css" rel="stylesheet">
    <style>
        .modal-backdrop {
            background-color: rgba(0, 0, 0, 0.5);
        }
    </style>
</head>
<body>
    <!-- 导航栏 -->
    <nav class="navbar navbar-expand-lg navbar-light bg-light shadow-sm">
        <div class="container">
            <a class="navbar-brand" href="/">VPS Value Tracker</a>
            <div class="d-flex align-items-center">
                {% if user %}
                    <div class="dropdown me-3">
                        <button class="btn btn-outline-secondary dropdown-toggle" type="button" data-bs-toggle="dropdown">
                            <i class="bi bi-person-circle"></i> {{ user.username }}
                        </button>
                        <ul class="dropdown-menu">
                            <li><a class="dropdown-item" href="#" onclick="logout()">登出</a></li>
                        </ul>
                    </div>
                    <button class="btn btn-primary" data-bs-toggle="modal" data-bs-target="#addVpsModal">
                        <i class="bi bi-plus-lg"></i> 添加 VPS
                    </button>
                {% else %}
                    <button class="btn btn-outline-primary" data-bs-toggle="modal" data-bs-target="#loginModal">
                        登录
                    </button>
                {% endif %}
            </div>
        </div>
    </nav>

    <div class="container py-4">
        <!-- 导出工具栏 -->
        <div class="d-flex justify-content-end mb-3">
            <div class="btn-group">
                <button class="btn btn-outline-secondary" onclick="exportMarkdown()">
                    <i class="bi bi-markdown"></i> 导出 Markdown
                </button>
                <button class="btn btn-outline-secondary" onclick="generateImage()">
                    <i class="bi bi-image"></i> 生成图片
                </button>
            </div>
        </div>

        <!-- VPS 表格 -->
        <div class="card shadow-sm">
            <div class="table-responsive">
                <table class="table table-hover mb-0">
                    <thead class="table-light">
                        <tr>
                            <th>商家</th>
                            <th>CPU</th>
                            <th>内存</th>
                            <th>硬盘</th>
                            <th>流量</th>
                            <th>价格</th>
                            <th>剩余价值(CNY)</th>
                            <th>开始时间</th>
                            <th>到期时间</th>
                        </tr>
                    </thead>
                    <tbody>
                        {% for vps in vps_list %}
                        <tr>
                            <td>{{ vps['vendor_name'] }}</td>
                            <td>{{ vps['cpu_cores'] }}核 {{ vps['cpu_model'] }}</td>
                            <td>{{ vps['memory'] }}GB</td>
                            <td>{{ vps['storage'] }}GB</td>
                            <td>{{ vps['bandwidth'] }}GB</td>
                            <td>{{ vps['price'] }} {{ vps['currency'] }}</td>
                            <td class="remaining-value" 
                                data-price="{{ vps['price'] }}"
                                data-currency="{{ vps['currency'] }}"
                                data-end-date="{{ vps['end_date'] }}">
                                计算中...
                            </td>
                            <td>{{ vps['start_date'] }}</td>
                            <td>{{ vps['end_date'] }}</td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
        </div>

        <!-- 登录模态框 -->
        <div class="modal fade" id="loginModal" tabindex="-1" aria-labelledby="loginModalLabel" aria-hidden="true">
            <div class="modal-dialog">
                <div class="modal-content">
                    <div class="modal-header">
                        <h5 class="modal-title" id="loginModalLabel">登录</h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
                    </div>
                    <div class="modal-body">
                        <form id="loginForm" onsubmit="return handleLogin(event)">
                            <div class="mb-3">
                                <label class="form-label">密码</label>
                                <input type="password" class="form-control" name="password" required>
                            </div>
                            <button type="submit" class="btn btn-primary">登录</button>
                        </form>
                    </div>
                </div>
            </div>
        </div>

        <!-- 添加VPS模态框 -->
        <div class="modal fade" id="addVpsModal" tabindex="-1" aria-labelledby="addVpsModalLabel" aria-hidden="true">
            <div class="modal-dialog modal-lg">
                <div class="modal-content">
                    <div class="modal-header">
                        <h5 class="modal-title" id="addVpsModalLabel">添加 VPS</h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
                    </div>
                    <div class="modal-body">
                        <form id="addVpsForm" onsubmit="return handleAddVps(event)">
                            <div class="row mb-3">
                                <div class="col-12">
                                    <label class="form-label">商家名称</label>
                                    <input type="text" class="form-control" name="vendor_name" required>
                                </div>
                            </div>
                            
                            <div class="row mb-3">
                                <div class="col-md-6">
                                    <label class="form-label">CPU核心数</label>
                                    <input type="number" class="form-control" name="cpu_cores" min="1" required>
                                </div>
                                <div class="col-md-6">
                                    <label class="form-label">CPU型号</label>
                                    <input type="text" class="form-control" name="cpu_model" required>
                                </div>
                            </div>

                            <div class="row mb-3">
                                <div class="col-md-4">
                                    <label class="form-label">内存(GB)</label>
                                    <input type="number" class="form-control" name="memory" min="0.5" step="0.5" required>
                                </div>
                                <div class="col-md-4">
                                    <label class="form-label">硬盘(GB)</label>
                                    <input type="number" class="form-control" name="storage" min="1" required>
                                </div>
                                <div class="col-md-4">
                                    <label class="form-label">流量(GB)</label>
                                    <input type="number" class="form-control" name="bandwidth" min="1" required>
                                </div>
                            </div>

                            <div class="row mb-3">
                                <div class="col-md-6">
                                    <label class="form-label">价格</label>
                                    <input type="number" class="form-control" name="price" min="0.01" step="0.01" required>
                                </div>
                                <div class="col-md-6">
                                    <label class="form-label">货币</label>
                                    <select class="form-select" name="currency" required>
                                        <option value="CNY">人民币 (CNY)</option>
                                        <option value="USD">美元 (USD)</option>
                                        <option value="EUR">欧元 (EUR)</option>
                                        <option value="GBP">英镑 (GBP)</option>
                                        <option value="JPY">日元 (JPY)</option>
                                        <option value="CAD">加元 (CAD)</option>
                                    </select>
                                </div>
                            </div>

                            <div class="row mb-3">
                                <div class="col-md-6">
                                    <label class="form-label">开始时间</label>
                                    <input type="date" class="form-control" name="start_date" required>
                                </div>
                                <div class="col-md-6">
                                    <label class="form-label">到期时间</label>
                                    <input type="date" class="form-control" name="end_date" required>
                                </div>
                            </div>

                            <div class="text-end">
                                <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">取消</button>
                                <button type="submit" class="btn btn-primary">添加</button>
                            </div>
                        </form>
                    </div>
                </div>
            </div>
        </div>

        <!-- 图片预览模态框 -->
        <div class="modal fade" id="imagePreviewModal" tabindex="-1" aria-labelledby="imagePreviewModalLabel" aria-hidden="true">
            <div class="modal-dialog modal-lg">
                <div class="modal-content">
                    <div class="modal-header">
                        <h5 class="modal-title" id="imagePreviewModalLabel">图片预览</h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
                    </div>
                    <div class="modal-body text-center">
                        <img id="previewImage" class="img-fluid" src="" alt="Preview">
                        <div class="mt-3">
                            <a id="imageDownloadLink" class="btn btn-primary" download="vps-table.png">
                                下载图片
                            </a>
                        </div>
                    </div>
                </div>
            </div>
        </div>

        <!-- 其他模态框保持不变 -->
    </div>

    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/js/bootstrap.bundle.min.js"></script>
    <script src="https://html2canvas.hertzen.com/dist/html2canvas.min.js"></script>
    <script>
        // 初始化所有模态框
        document.addEventListener('DOMContentLoaded', function() {
            const modals = document.querySelectorAll('.modal');
            modals.forEach(modalEl => {
                new bootstrap.Modal(modalEl);
            });
        });

        // 登出功能
        async function logout() {
            const response = await fetch('/api/logout', {
                method: 'POST'
            });
            if (response.ok) {
                window.location.reload();
            }
        }

        // 导出 Markdown
        function exportMarkdown() {
            const table = document.querySelector('table');
            let md = '| ';
            
            // 表头
            const headers = table.querySelectorAll('thead th');
            headers.forEach(header => {
                md += header.textContent + ' | ';
            });
            md += '\\n|';
            
            // 分隔线
            headers.forEach(() => {
                md += ' --- |';
            });
            md += '\\n';
            
            // 数据行
            const rows = table.querySelectorAll('tbody tr');
            rows.forEach(row => {
                md += '| ';
                row.querySelectorAll('td').forEach(cell => {
                    md += cell.textContent.trim() + ' | ';
                });
                md += '\\n';
            });
            
            // 复制到剪贴板
            navigator.clipboard.writeText(md).then(() => {
                alert('Markdown 表格已复制到剪贴板');
            });
        }

        // 生成图片
        async function generateImage() {
            const table = document.querySelector('.card');
            const canvas = await html2canvas(table);
            
            // 转换为图片
            const imageData = canvas.toDataURL('image/png');
            
            // 上传到服务器
            const response = await fetch('/api/upload-image', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ image: imageData })
            });
            
            if (response.ok) {
                const { url } = await response.json();
                
                // 显示预览
                document.getElementById('previewImage').src = url;
                document.getElementById('imageDownloadLink').href = url;
                new bootstrap.Modal(document.getElementById('imagePreviewModal')).show();
            }
        }

        // 修改登录处理函数
        async function handleLogin(event) {
            event.preventDefault();
            const form = event.target;
            const formData = new FormData();
            formData.append('username', 'admin');  // 固定用户名
            formData.append('password', form.password.value);  // 获取密码
            
            try {
                const response = await fetch('/api/login', {
                    method: 'POST',
                    body: formData
                });
                
                if (response.ok) {
                    window.location.reload();
                } else {
                    const error = await response.json();
                    alert(error.detail || '登录失败');
                }
            } catch (error) {
                console.error('Error:', error);
                alert('登录失败: 网络错误');
            }
            return false;
        }

        // 其他 JavaScript 代码保持不变
    </script>
</body>
</html>
'''

# 配置部分
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")
if not ADMIN_PASSWORD:
    raise ValueError("ADMIN_PASSWORD environment variable must be set")

# 修改数据库初始化函数
async def init_db():
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE,
                    password TEXT
                )
            ''')
            await db.execute('''
                CREATE TABLE IF NOT EXISTS vps (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    vendor_name TEXT,
                    cpu_cores INTEGER,
                    cpu_model TEXT,
                    memory INTEGER,
                    storage INTEGER,
                    bandwidth INTEGER,
                    price REAL,
                    currency TEXT,
                    start_date TEXT,
                    end_date TEXT,
                    user_id INTEGER
                )
            ''')
            # 创建默认管理员账号
            hashed_password = pwd_context.hash(ADMIN_PASSWORD)
            try:
                await db.execute('INSERT INTO users (username, password) VALUES (?, ?)',
                               ['admin', hashed_password])
                await db.commit()
                logger.info("Created default admin user")
            except:
                # 更新已存在的管理员密码
                await db.execute('UPDATE users SET password = ? WHERE username = ?',
                               [hashed_password, 'admin'])
                await db.commit()
                logger.info("Updated admin password")
                
            logger.info("Database initialized successfully")
    except Exception as e:
        logger.error(f"Database initialization error: {e}", exc_info=True)
        raise

@app.on_event("startup")
async def startup_event():
    logger.info(f"ADMIN_PASSWORD is set to: {ADMIN_PASSWORD}")
    if not ADMIN_PASSWORD:
        raise ValueError("ADMIN_PASSWORD environment variable must be set")
    await init_db()

# 汇率缓存
exchange_rates_cache = {"timestamp": 0, "rates": {}}

# 辅助函数
async def get_exchange_rates():
    now = datetime.now().timestamp()
    if now - exchange_rates_cache["timestamp"] > 86400:  # 24小时更新一次
        async with aiohttp.ClientSession() as session:
            async with session.get(f"http://data.fixer.io/api/latest?access_key={FIXER_API_KEY}&base=EUR") as response:
                data = await response.json()
                if data["success"]:
                    exchange_rates_cache["rates"] = data["rates"]
                    exchange_rates_cache["timestamp"] = now
    return exchange_rates_cache["rates"]

async def convert_to_cny(amount: float, currency: str) -> float:
    if currency == "CNY":
        return amount
    rates = await get_exchange_rates()
    if currency in rates and "CNY" in rates:
        # 先转换为EUR，再转换为CNY
        eur_amount = amount / rates[currency]
        return eur_amount * rates["CNY"]
    return amount

async def calculate_remaining_value(price: float, currency: str, end_date: str) -> float:
    end = datetime.strptime(end_date, "%Y-%m-%d")
    days_remaining = (end - datetime.now()).days
    if days_remaining < 0:
        return 0
    yearly_value = await convert_to_cny(price, currency)
    return round(yearly_value * days_remaining / 365, 2)

# API路由实现
@app.post("/api/login")
async def login(username: str = Form(...), password: str = Form(...)):
    try:
        logger.info(f"Login attempt with password: {password}")
        logger.info(f"Expected password: {ADMIN_PASSWORD}")
        
        # 直接比较密码
        if password == ADMIN_PASSWORD:
            token = jwt.encode({"sub": "admin"}, SECRET_KEY)
            response = JSONResponse(content={"success": True})
            response.set_cookie(key="session", value=token, httponly=True)
            logger.info("Login successful")
            return response
        else:
            logger.warning("Invalid password")
            raise HTTPException(status_code=401, detail="密码错误")
            
    except Exception as e:
        logger.error(f"Login error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="登录失败")

@app.post("/api/vps")
async def add_vps(vps_data: dict, session: str = Cookie(None)):
    try:
        if not session:
            raise HTTPException(status_code=401)
        
        try:
            payload = jwt.decode(session, SECRET_KEY)
            username = payload["sub"]
        except JWTError:
            raise HTTPException(status_code=401)

        async with aiosqlite.connect(DB_PATH) as db:
            # 获取用户ID
            async with db.execute('SELECT id FROM users WHERE username = ?', [username]) as cursor:
                user = await cursor.fetchone()
                if not user:
                    raise HTTPException(status_code=401)
                    
            # 添加VPS信息，确保数值类型正确
            try:
                await db.execute('''
                    INSERT INTO vps (
                        vendor_name, cpu_cores, cpu_model, memory, storage, bandwidth,
                        price, currency, start_date, end_date, user_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', [
                    vps_data.get("vendor_name"),
                    float(vps_data.get("cpu_cores", 0)),  # 转换为float
                    vps_data.get("cpu_model", ""),
                    float(vps_data.get("memory", 0)),     # 转换为float
                    float(vps_data.get("storage", 0)),    # 转换为float
                    float(vps_data.get("bandwidth", 0)),  # 转换为float
                    float(vps_data.get("price", 0)),
                    vps_data.get("currency", "CNY"),
                    vps_data.get("start_date", datetime.now().strftime("%Y-%m-%d")),
                    vps_data.get("end_date"),
                    user[0]
                ])
                await db.commit()
                return {"success": True}
            except Exception as e:
                logger.error(f"Database error while adding VPS: {e}")
                raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        logger.error(f"Error in add_vps: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/vps")
async def get_vps():
    async with aiosqlite.connect('vps.db') as db:
        db.row_factory = aiosqlite.Row
        async with db.execute('SELECT * FROM vps ORDER BY end_date DESC') as cursor:
            vps_list = await cursor.fetchall()
            
        # 计算剩余价值
        result = []
        for vps in vps_list:
            vps_dict = dict(vps)
            vps_dict["remaining_value"] = await calculate_remaining_value(
                vps["price"], vps["currency"], vps["end_date"]
            )
            result.append(vps_dict)
            
    return result

# 修改首页路由，添加用户信息
@app.get("/", response_class=HTMLResponse)
async def home(request: Request, session: Optional[str] = Cookie(None)):
    try:
        user = None
        if session:
            try:
                payload = jwt.decode(session, SECRET_KEY)
                user = {"username": payload["sub"]}
            except JWTError as e:
                logger.warning(f"Invalid session token: {e}")
                
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute('SELECT * FROM vps ORDER BY end_date DESC') as cursor:
                vps_list = [dict(row) for row in await cursor.fetchall()]
                
        return templates.TemplateResponse("base.html", {
            "request": request,
            "user": user,
            "vps_list": vps_list
        })
    except Exception as e:
        logger.error(f"Home page error: {e}", exc_info=True)
        raise

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Global error: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"}
    ) 

@app.get("/api/convert")
async def convert_currency(amount: float, currency: str):
    try:
        value = await convert_to_cny(amount, currency)
        return {"value": value}
    except Exception as e:
        logger.error(f"Currency conversion error: {e}", exc_info=True)
        raise 

# 创建图片保存目录
IMAGES_DIR = Path('static/images')
IMAGES_DIR.mkdir(parents=True, exist_ok=True)

# 添加静态文件服务
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.post("/api/logout")
async def logout():
    response = JSONResponse(content={"success": True})
    response.delete_cookie(key="session")
    return response

@app.post("/api/upload-image")
async def upload_image(data: dict):
    try:
        # 解码base64图片数据
        image_data = data['image'].split(',')[1]
        image_bytes = base64.b64decode(image_data)
        
        # 生成文件名
        filename = f"vps-table-{datetime.now().strftime('%Y%m%d-%H%M%S')}.png"
        file_path = IMAGES_DIR / filename
        
        # 保存图片
        with open(file_path, 'wb') as f:
            f.write(image_bytes)
            
        # 返回图片URL（使用完整域名）
        image_url = f"/static/images/{filename}"
        full_url = f"{BASE_URL}{image_url}"
            
        return {
            "success": True,
            "url": image_url,
            "full_url": full_url
        }
    except Exception as e:
        logger.error(f"Error saving image: {e}")
        raise HTTPException(status_code=500, detail="Failed to save image") 

@app.get("/api/vps/{vps_id}")
async def get_vps_by_id(vps_id: int, session: str = Cookie(None)):
    if not session:
        raise HTTPException(status_code=401)
    
    try:
        payload = jwt.decode(session, SECRET_KEY)
    except JWTError:
        raise HTTPException(status_code=401)

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute('SELECT * FROM vps WHERE id = ?', [vps_id]) as cursor:
            vps = await cursor.fetchone()
            if vps:
                return dict(vps)
            raise HTTPException(status_code=404, detail="VPS not found")

@app.put("/api/vps/{vps_id}")
async def update_vps(vps_id: int, vps_data: dict, session: str = Cookie(None)):
    if not session:
        raise HTTPException(status_code=401)
    
    try:
        payload = jwt.decode(session, SECRET_KEY)
    except JWTError:
        raise HTTPException(status_code=401)

    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute('''
                UPDATE vps SET 
                    vendor_name = ?, cpu_cores = ?, cpu_model = ?, 
                    memory = ?, storage = ?, bandwidth = ?,
                    price = ?, currency = ?, start_date = ?, end_date = ?
                WHERE id = ?
            ''', [
                vps_data.get("vendor_name"),
                float(vps_data.get("cpu_cores", 0)),  # 改为 float
                vps_data.get("cpu_model", ""),
                float(vps_data.get("memory", 0)),     # 改为 float
                float(vps_data.get("storage", 0)),    # 改为 float
                float(vps_data.get("bandwidth", 0)),  # 改为 float
                float(vps_data.get("price", 0)),
                vps_data.get("currency", "CNY"),
                vps_data.get("start_date"),
                vps_data.get("end_date"),
                vps_id
            ])
            await db.commit()
            return {"success": True}
        except Exception as e:
            logger.error(f"Database error while updating VPS: {e}")
            raise HTTPException(status_code=500, detail=str(e))  # 返回具体错误信息

@app.delete("/api/vps/{vps_id}")
async def delete_vps(vps_id: int, session: str = Cookie(None)):
    if not session:
        raise HTTPException(status_code=401)
    
    try:
        payload = jwt.decode(session, SECRET_KEY)
    except JWTError:
        raise HTTPException(status_code=401)

    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute('DELETE FROM vps WHERE id = ?', [vps_id])
            await db.commit()
            return {"success": True}
        except Exception as e:
            logger.error(f"Database error while deleting VPS: {e}")
            raise HTTPException(status_code=500, detail="Failed to delete VPS") 

# 添加环境变量
DOMAIN = os.getenv("DOMAIN", "localhost")
BASE_URL = os.getenv("BASE_URL", f"http://{DOMAIN}") 