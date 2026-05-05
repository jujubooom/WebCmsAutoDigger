---
name: webcms-installer
description: 通过 Docker 构建和安装 Web CMS 项目。
allowed-tools: [Read, Glob, Grep, Bash, Write, Edit, WebFetch]
---

# Web CMS Docker 安装器

## 1. 分析项目

- 读 README.md / INSTALL.md，确定技术栈和 PHP 版本要求
- 检查 composer.json，确定需要的 PHP 扩展（mysqli, gd, xml, mbstring 等）
- 检查配置文件中的数据库类型

## 2. 构建

- 编写 Dockerfile：选择合适的 PHP 基础镜像（老 CMS 用 php:7.4-apache），启用 mod_rewrite + AllowOverride All
- `docker build -t cms .` 构建，失败则查看错误调整 Dockerfile
- 尽量使用本地存在的镜像层，减少构建时间

## 3. 运行
- 先寻找可用端口，避免冲突
- 确定端口（默认 8080），`docker run -d --name cms -p HOST:80 cms`
- `for i in $(seq 1 30); do curl -s http://127.0.0.1:HOST/ && break; sleep 2; done` 等就绪

## 4. Web 安装

- 访问 `/install` 或根路径，提取表单字段和 CSRF 令牌
- 管理员用 admin/admin123，数据库如有则填已有凭据
- 用 curl 携带 cookie 逐步骤提交安装表单
- 遇到前端加密：先找明文传输路径，不行则 docker exec 进容器直接写数据库
- 遇到验证码：分析验证码逻辑，看看能不能通过操作数据库绕过，如果不能则尝试直接修改源码做最小改动绕过还要附上注释说明，千万不能尝试下载安装OCR去识别验证码，这个太重了不实用
- 如果web正常跑起来了，但是安装流程或者纯web代码自身问题非镜像或者容器问题比如权限，则直接使用docker exec修复，不用重装，如果确实是dockerfile问题，比如版本不对或者缺扩展导致的安装问题，则修改dockerfile重建重装

## 5. 验证

- curl 确认首页和管理后台可访问
- 用管理员凭据登录，确认后台正常

