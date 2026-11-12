# DB

把飞牛影视的数据库放在这里，默认文件名：

```text
DB/trimmedia.db
```

飞牛 NAS 上的原始位置：

```text
/usr/local/apps/@appdata/trim.media/database/trimmedia.db
```

也可以只读挂载目录，然后在「系统设置」里改成实际路径。

> 数据库文件包含个人观看记录，已被 `.gitignore` 忽略，请不要提交到仓库。
> FN2Trakt 以只读模式打开它，不会写入或修改。
