# 阿里云 OSS 图片配置

店小秘导入模板只接受公网 HTTP/HTTPS 图片地址，本项目会在导出模板前把图片镜像到阿里云 OSS。

## 需要准备

1. 开通阿里云 OSS。
2. 创建 Bucket，建议选择国内地域。
3. Bucket 或绑定域名需要能公网读取图片。
4. 创建 AccessKey，至少需要对该 Bucket 有 `PutObject` 权限。

## 后端环境变量

启动后端前设置这些变量：

```powershell
$env:ALIYUN_OSS_ENABLED="1"
$env:ALIYUN_OSS_ACCESS_KEY_ID="你的AccessKeyId"
$env:ALIYUN_OSS_ACCESS_KEY_SECRET="你的AccessKeySecret"
$env:ALIYUN_OSS_ENDPOINT="oss-cn-hangzhou.aliyuncs.com"
$env:ALIYUN_OSS_BUCKET="你的Bucket名称"
$env:ALIYUN_OSS_PUBLIC_BASE_URL="https://你的Bucket名称.oss-cn-hangzhou.aliyuncs.com"
$env:ALIYUN_OSS_OBJECT_PREFIX="temu-listing"
```

`ALIYUN_OSS_PUBLIC_BASE_URL` 可以换成你绑定到 OSS/CDN 的 HTTPS 域名。

## 图片字段流转

图片数据结构保留三层地址：

- `sourceUrl` / `sourceCloudUrl`：原始货源图片。
- `displayUrl` / `displayCloudUrl`：当前展示图片。
- `editedUrl` / `editedCloudUrl`：ChatGPT 或 ComfyUI 统一画风后的图片。

导出策略：

- 铺货模式优先使用 `sourceCloudUrl`，没有则上传 `sourceUrl` 到 OSS。
- 精铺模式优先使用 `editedCloudUrl`，没有则上传 `editedUrl`，再回退展示图和原图。

如果没有设置 `ALIYUN_OSS_ENABLED=1`，导出会保留原 URL，方便本地开发。
