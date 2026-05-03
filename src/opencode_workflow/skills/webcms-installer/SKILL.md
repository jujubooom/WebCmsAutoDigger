---
name: webcms-installer
description: 通过 Docker 构建和安装 Web CMS 项目。当用户想要从当前目录 docker 化、部署、安装或运行 Web CMS（WordPress、Drupal、Joomla、Typecho、自定义 PHP CMS、Node CMS、Python CMS 等）时使用。触发词："install this CMS"、"dockerize this project"、"build and run this web project"、"deploy this"、"set up this CMS"。
argument-hint: [port]
allowed-tools: [Read, Glob, Grep, Bash, Write, Edit, WebFetch]
---

# Web CMS Docker 安装器

从当前工作目录 docker 化、构建并安装 Web CMS。目标是一个运行中的服务，并最终报告 URL、端口和凭据。

## 阶段

### 阶段 1 — 项目分析

**1a. 首先阅读 README。**

按顺序检查以下文件：`README.md`、`README`、`INSTALL.md`、`INSTALL`、`SETUP.md`、`BUILDING.md`、`DEPLOY.md`。读取所有存在的文件。提取：技术栈、PHP/Node/Python 版本要求、数据库类型、Web 服务器需求、安装步骤、凭据。

**1b. 识别技术栈。**

| 信号 | 技术栈 |
|---|---|
| `composer.json` | PHP |
| `package.json` 含 `next`/`react`/`vue`/`express`/`strapi`/`payload`/`keystone` | Node |
| `requirements.txt` / `pyproject.toml` / `setup.py` 含 `django`/`flask`/`wagtail`/`mezzanine` | Python |
| `Gemfile` 含 `rails`/`jekyll` | Ruby |
| `wp-config.php` / `wp-includes/` | WordPress |
| `index.php` + `wp-` 前缀文件 | WordPress |
| `core/` + `composer.json` 含 `drupal/` | Drupal |
| `configuration.php` + `libraries/` | Joomla |
| `admin/` + `install/` + `*.php` 文件 | 通用 PHP CMS |
| 已存在 `Dockerfile` | 检查是否可用 |

**1c. 确定数据库需求。**

- 检查配置文件（`.env`、`.env.example`、`config/database.php`、`wp-config.php`、`settings.py`）中的数据库引擎、主机、端口、名称、用户名、密码。
- 如果是 SQLite：不需要单独的数据库容器。
- 如果是 MySQL/MariaDB/PostgreSQL：规划 `docker-compose` 或链接容器设置，或使用已有的主机网络数据库。

**1d. 检查已有的 Dockerfile。**

如果已经存在 `Dockerfile` 或 `docker-compose.yml`，评估是否足够。如果足够，直接使用。如果不够，记录缺少的部分并补充。

### 阶段 2 — 编写 Dockerfile

**2a. 选择基础镜像。**

| 技术栈 | 基础镜像 |
|---|---|
| PHP (Apache) | `php:8.2-apache`（根据项目要求调整版本） |
| PHP (Nginx) | `php:8.2-fpm` + `nginx:alpine`（双阶段或 compose） |
| Node | `node:22-alpine` 或 `node:22` |
| Python/Django | `python:3.12-slim` |
| Ruby/Rails | `ruby:3.3-slim` |

优先使用具体版本标签而非 `latest`。

**2b. PHP 特定模式。**

对于 PHP CMS 项目，Dockerfile 必须：
- 安装 PHP 扩展：`mysqli`、`pdo_mysql`、`pdo_pgsql`、`gd`、`mbstring`、`xml`、`zip`、`curl`、`intl`、`opcache`。检查项目实际需要哪些。
- 启用 Apache mod_rewrite：`a2enmod rewrite`
- 在 Apache 配置中设置 `AllowOverride All`，使 `.htaccess` 文件生效
- 如果入口点在子目录中（如 `public/`、`web/`、`html/`），设置正确的 `DocumentRoot`
- 修复文件权限：`chown -R www-data:www-data /var/www/html`
- 将文件复制到 `/var/www/html`

**2c. Node 特定模式。**

- `WORKDIR /app`
- 先复制 `package.json` 和 `package-lock.json`，然后 `RUN npm ci`（如果没有 lock 文件则用 `npm install`）
- 复制其余源代码
- 如果需要构建步骤：`RUN npm run build`
- 暴露应用的端口（通常是 3000）
- `CMD ["node", "server.js"]` 或 `CMD ["npm", "start"]`

**2d. Python 特定模式。**

- 设置 virtualenv 或使用系统 pip
- `COPY requirements.txt . && RUN pip install -r requirements.txt`
- 在入口脚本中运行迁移
- 使用 gunicorn 或 uwsgi 作为应用服务器

**2e. 文件权限（对 Linux 主机至关重要）。**

许多镜像中容器进程以非 root 用户运行（如 PHP 的 `www-data`、Node 的 `node`）。显式设置复制文件的所有权为运行时用户。

**2f. 编写 Dockerfile。**

在项目根目录创建 `Dockerfile`。如果已存在且足够用，跳过此步。否则编写新的。Dockerfile 应具备生产可用性但保持简洁——除非项目有构建步骤，否则不使用多阶段构建。

### 阶段 3 — 端口和冲突检查

**3a. 确定容器端口。**

容器内应用监听的已知端口：
- PHP-Apache：`80`
- Node 开发服务器：`3000`（或从代码 / `.env` 的 `PORT` 变量获取）
- Python/Gunicorn：`8000`
- Nginx：`80`

**3b. 检查主机端口可用性。**

运行以下检查：
```bash
ss -tlnp | grep ":PORT "         # 检查端口是否已被占用
docker ps --format '{{.Ports}}'  | grep -oP '\d+(?=->)'  # 检查 docker 端口映射
```

如果用户通过 `$ARGUMENTS` 指定了端口，使用该端口。否则，默认使用一个合理的端口（如 8080）并检查可用性。如果被占用，递增：8081、8082……直到找到可用端口。构建前报告所选端口。

**3c. 检查容器名称冲突。**

```bash
docker ps -a --format '{{.Names}}' | grep "^PROJECT-cms$"
```

如果名称 `PROJECT-cms` 已被占用，追加后缀（`-1`、`-2`）。或者在用户同意后删除已停止的容器。

### 阶段 4 — 构建

**4a. 检查本地已有镜像。**

构建前，先检查本地是否已有可用的镜像：

```bash
# 查看本地已有的相关镜像
docker images | grep -i "php\|node\|python\|nginx\|apache" | grep -v "<none>"

# 查看是否有之前构建的同一项目镜像
docker images PROJECT-cms
```

如果本地已有匹配项目技术栈的镜像（如 `php:7.4-apache` 对应 DedeCMS），直接使用，跳过构建步骤。如果之前构建过同一项目的镜像且代码无变化，同样直接复用。

**4b. 构建镜像。**

```bash
docker build -t PROJECT-cms:latest .
```

注意构建错误。常见失败：
- 缺少 PHP 扩展 → 添加到 Dockerfile
- npm install 失败 → 检查 Node 版本兼容性
- pip install 失败 → 检查 Python 版本
- `COPY` 权限错误 → 检查 `.dockerignore`

**4c. 如果构建失败，仔细阅读错误。**

- 查看失败的行
- 诊断：缺少依赖？网络问题？版本冲突？
- 修复 Dockerfile 并重新构建
- 不要盲目重试——修复根本原因

### 阶段 5 — 运行

**5a. 启动容器。**

```bash
docker run -d --name PROJECT-cms -p HOST_PORT:CONTAINER_PORT PROJECT-cms:latest
```

如果项目需要环境变量（数据库凭据等），用 `-e` 传递：
```bash
docker run -d --name PROJECT-cms -p HOST_PORT:80 \
  -e DB_HOST=host.docker.internal \
  -e DB_DATABASE=cms \
  -e DB_USERNAME=root \
  -e DB_PASSWORD=secret \
  PROJECT-cms:latest
```

在 Linux 上访问主机网络数据库时，使用 `--add-host host.docker.internal:host-gateway`（Docker 20.10+）。

**5b. 检查容器是否实际在运行。**

```bash
docker ps --filter name=PROJECT-cms --format '{{.Status}}'
```

如果立即退出：
```bash
docker logs PROJECT-cms --tail 50
```

常见启动失败：
- Apache 无法绑定容器内 80 端口 → 存在其他进程
- MySQL 连接被拒绝 → 数据库未运行或无法访问
- 缺少配置文件 → 需要将 `.env.example` 复制为 `.env`
- 文件权限被拒绝 → 在 Dockerfile 中修复所有权
- PHP 致命错误 → 检查 PHP 版本兼容性

**5c. 等待服务就绪。**

轮询直到服务响应：
```bash
for i in $(seq 1 30); do
  if curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:HOST_PORT/ | grep -qE '^(2|3|4)'; then
    echo "服务已启动"
    break
  fi
  sleep 2
done
```

4xx 响应仍然表示服务器在运行——可能只是需要安装。

### 阶段 6 — Web 安装

许多 CMS 系统需要通过浏览器进行设置向导。以编程方式处理。

**6a. 检测安装路径。**

常见安装 URL：`/`、`/install`、`/install.php`、`/setup`、`/admin/install`、`/core/install.php`（Drupal）、`/wp-admin/install.php`（WordPress）。

获取根页面并查找：
- 重定向到安装路径（跟踪它们）
- action 中包含 `install` 或 `setup` 的表单
- CSRF 令牌（在隐藏输入中查找 `csrf`、`_token`、`nonce`、`token`）

```bash
curl -s -L http://127.0.0.1:HOST_PORT/
```

**6b. 数据库配置步骤。**

大多数安装器会询问数据库凭据。常见表单字段：
- `db_host`、`db_name`、`db_user`、`db_pass`、`db_prefix`
- `database[host]`、`database[name]` 等
- SQLite：只有一个路径字段

查看表单结构：
```bash
curl -s http://127.0.0.1:HOST_PORT/install | grep -i '<form\|<input\|<select'
```

提取字段名称、隐藏输入（尤其是 CSRF 令牌）和 action URL。

**6c. 站点配置步骤。**

常见表单字段：
- `site_name`、`admin_email`、`admin_user`、`admin_pass`、`admin_pass2`
- WordPress：`weblog_title`、`user_name`、`admin_email`、`pass1`

**6d. 按顺序提交安装表单。**

对于向导中的每一步，构造 POST 请求：
```bash
curl -s -L -X POST "http://127.0.0.1:HOST_PORT/install" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "field1=value1&field2=value2&csrf_token=abc123" \
  -c /tmp/cms_cookies.txt -b /tmp/cms_cookies.txt
```

关键细节：
- 始终使用 `-c` 和 `-b` 在请求之间持久化 cookie/会话
- 提交前始终从表单的隐藏输入中提取 CSRF 令牌
- 使用 `-L` 跟踪重定向到下一步
- 检查响应正文中的错误消息
- 检查 HTTP 状态码——200 但带有错误文本表示表单验证失败；提取错误消息并修复

**6e. 处理 CSRF 令牌。**

```bash
CSRF=$(curl -s -c /tmp/cms_cookies.txt http://127.0.0.1:HOST_PORT/install | \
  grep -oP '<input[^>]*name="(csrf_token|_token|nonce)"[^>]*value="\K[^"]+')
```

如果令牌在 meta 标签中：
```bash
CSRF=$(curl -s -c /tmp/cms_cookies.txt http://127.0.0.1:HOST_PORT/install | \
  grep -oP '<meta[^>]*name="csrf-token"[^>]*content="\K[^"]+')
```

**6f. 处理多步骤向导。**

每次 POST 后，检查响应：
- 如果重定向到下一步（3xx），跟踪并继续
- 如果显示相同表单并有错误，阅读错误文本并调整
- 如果显示成功页面或重定向到 `/`，安装完成

**6g. 填写管理员凭据。**

如果安装器要求提供凭据，直接使用弱口令，不要生成强密码：
- 管理员用户名：`admin`
- 管理员密码：使用弱口令如 `admin`、`admin123`、`123456`
- 管理员邮箱：`admin@cms.local`
- 站点名称：从目录名获取或使用 `CMS Site`

**6h. 处理前端加密。**

如果安装表单对密码做了前端加密（如 JS 加密后提交），按以下顺序处理：

1. **先尝试抓取明文传输路径**：部分 CMS 同时支持明文和加密两种提交方式，检查是否有 `password_plain` 之类的字段。

2. **读源码破解加密逻辑**：找到加密相关的 JS 文件，用 `curl` 拉取后在本地分析。常见模式：
   - RSA 公钥加密 → 通常 JS 里有公钥，可以直接用 openssl 或 node 做相同加密
   - MD5/sha1 哈希 → 直接对弱口令做同样的哈希
   - 自定义编码 → 照着 JS 逻辑复现

   ```bash
   # 抓取页面中引用的 JS 文件
   curl -s http://127.0.0.1:HOST_PORT/install | grep -oP 'src="\K[^"]+\.js'
   # 逐个下载分析，搜索 encrypt、password、rsa、md5 等关键字
   curl -s http://127.0.0.1:HOST_PORT/path/to/main.js | grep -i 'encrypt\|password\|rsa\|md5\|encode'
   ```

3. **如果加密逻辑复杂无法复现，直接写数据库**：绕过 Web 安装器，用 `docker exec` 进容器直接操作数据：
   ```bash
   # MySQL/MariaDB - 先找到正确的密码哈希算法
   docker exec CONTAINER mysql -hHOST -uUSER -pPASS DBNAME \
     -e "SELECT password FROM admin_user LIMIT 1"  # 查看已有密码哈希格式
   # 用已知哈希替换（如 CMS 默认安装后的 admin 的密码哈希，或自己生成对应哈希）
   docker exec CONTAINER mysql -hHOST -uUSER -pPASS DBNAME \
     -e "UPDATE admin_user SET password='KNOWN_HASH' WHERE username='admin'"
   
   # SQLite
   docker exec CONTAINER sqlite3 /path/to/database.db \
     "UPDATE users SET password='HASH' WHERE username='admin'"
   ```

   注意：写数据库前先查看表结构，确认表名和字段名，以及密码哈希的格式。部分 CMS 有现成的密码哈希生成脚本，优先用那个。如果 CMS 代码里有 `password_hash` 函数调用，可以在容器里直接写一个 PHP 脚本生成哈希：
   ```bash
   docker exec CONTAINER php -r "echo password_hash('admin', PASSWORD_BCRYPT);"
   ```

### 阶段 7 — 运行时错误排查

当 curl 返回意外结果时：

**7a. 检查 docker 日志。**
```bash
docker logs PROJECT-cms --tail 100 2>&1
```
查找 PHP 警告、致命错误、数据库连接错误、文件未找到错误。

**7b. 检查容器内的 Apache/Nginx 错误日志。**
```bash
docker exec PROJECT-cms cat /var/log/apache2/error.log
docker exec PROJECT-cms cat /var/log/nginx/error.log
```

**7c. 检查 PHP 错误日志。**
```bash
docker exec PROJECT-cms cat /var/log/php_errors.log 2>/dev/null
docker exec PROJECT-cms find / -name "error_log" -exec cat {} \; 2>/dev/null
```

**7d. 常见 PHP CMS 错误。**
| 症状 | 可能原因 | 修复方法 |
|---|---|---|
| 空白页 / 500 | 缺少 PHP 扩展 | 添加到 Dockerfile，重新构建 |
| 数据库"Connection refused" | 数据库未运行或主机错误 | 使用 `host.docker.internal` 或 docker 网络 |
| 数据库"Access denied" | 凭据错误 | 检查项目默认值 |
| "Table not found" | 数据库存在但没有表 | 通过安装向导运行 |
| 文件权限错误 | 所有权不正确 | 使用 `docker exec` 修复（见下文） |
| ".htaccess" 不生效 | mod_rewrite 未启用 | `a2enmod rewrite` + `AllowOverride All` |
| 内存耗尽 | PHP 内存限制太低 | 传递 `-e PHP_MEMORY_LIMIT=256M` |

**7e. 用 Docker API 原地修复，不要重装**

很多运行时问题可以用 `docker exec` 原地修复，避免重建镜像和重装：

```bash
# 文件权限问题 - 最常见
docker exec CONTAINER chmod -R 777 /var/www/html/data/ /var/www/html/uploads/ /var/www/html/a/ /var/www/html/plus/ /var/www/html/dede/ /var/www/html/templets/
docker exec CONTAINER chown -R www-data:www-data /var/www/html/

# 目录权限不对导致安装失败
docker exec CONTAINER chmod 777 /var/www/html/data/
docker exec CONTAINER chmod 777 /var/www/html/uploads/
docker exec CONTAINER chmod 777 /var/www/html/templets/

# 修复后重新提交安装表单
curl -s -L -X POST "http://127.0.0.1:HOST_PORT/install/index.php" \
  -d "step=4&dbhost=...&dbuser=...&dbpwd=...&dbname=..."
```

记住这个原则：只要容器还在运行，能用 `docker exec` 解决的问题就绝不重建。

**7f. 常见 Node CMS 错误。**
| 症状 | 可能原因 | 修复方法 |
|---|---|---|
| `MODULE_NOT_FOUND` | 缺少 npm install | 检查 Dockerfile 安装步骤 |
| 构建错误 | Node 版本不匹配 | 调整基础镜像版本 |
| `EADDRINUSE` | 容器内端口已被使用 | 检查 CMD，检查僵尸进程 |

**7g. 如果 Web 安装器卡住（无限重定向循环）。**
- 检查 `.htaccess` 重写规则
- 检查 `mod_rewrite` 是否启用
- 检查安装器是否需要 HTTPS（在报告中注明，或使用自签名证书）

**7h. PHP 版本兼容性问题**

DedeCMS 5.7 等老版本 CMS 不支持 PHP 8.x。常见错误：
- `Call to undefined function get_magic_quotes_gpc()` — PHP 8 移除此函数

解决方案：降级到 PHP 7.4：
```dockerfile
FROM php:7.4-apache
```

不要试图在 PHP 8 上修代码，老 CMS 代码不兼容 PHP 8，直接换基础镜像。

### 阶段 8 — 最终验证

**8a. 确认服务可访问。**
```bash
curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:HOST_PORT/
```

**8b. 尝试管理员登录页面。**
```bash
curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:HOST_PORT/admin
```

**8c. 通过登录验证凭据有效。**
```bash
curl -s -L -X POST "http://127.0.0.1:HOST_PORT/admin/login" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=ADMIN_USER&password=ADMIN_PASS" \
  -c /tmp/cms_login_cookies.txt -b /tmp/cms_cookies.txt
```
检查响应是否显示管理后台内容（而不是再次显示登录表单）。

### 阶段 9 — 最终报告

打印清晰的摘要：

```
=== Web CMS 安装完成 ===

  服务 URL:      http://127.0.0.1:HOST_PORT
  容器:          PROJECT-cms
  镜像:          PROJECT-cms:latest

  管理 URL:      http://127.0.0.1:HOST_PORT/admin
  管理员用户名:  admin
  管理员密码:    XXXXXXXXXXXXXXXX

  数据库主机:    host.docker.internal（或使用的 DB_HOST）
  数据库名称:    cms
  数据库用户:    root

  停止:          docker stop PROJECT-cms
  启动:          docker start PROJECT-cms
  删除:          docker rm -f PROJECT-cms

=== 已创建文件 ===
  Dockerfile      （如果已创建）
```

---

## 防御性检查清单

在每次重大操作之前，考虑以下事项：

- [ ] 主机端口是否空闲？（用 `ss` 和 `docker ps` 检查）
- [ ] 容器名称是否可用？
- [ ] 是否有已有的 Dockerfile 需要先阅读？
- [ ] 是否需要 `.dockerignore` 以避免复制 `.git`、`node_modules`、`vendor`？
- [ ] 应用是否会尝试绑定容器内冲突的端口？
- [ ] 应用是否需要数据库？是否有数据库在运行且可访问？
- [ ] 是否有之前尝试留下的容器需要清理？
- [ ] Docker 守护进程是否在运行？(`docker info` > /dev/null)
- [ ] 是否有足够的磁盘空间用于构建？(`df -h .`)
- [ ] 容器内文件权限是否对运行时用户正确？
- [ ] 安装向导是否完成了所有步骤，还是卡在中间？
- [ ] 应用是否需要对某些目录（uploads、cache、logs）的写权限？
- [ ] **容器在运行但有问题？用 docker exec 修复，不要重装**

## 完成后

不要留下临时文件。清理：
```bash
rm -f /tmp/cms_cookies.txt /tmp/cms_login_cookies.txt
```
