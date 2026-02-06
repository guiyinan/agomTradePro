# 文档链接校验报告

## 基本信息

- 生成日期：2026-02-06
- 校验范围：`docs/**/*.md`
- 校验规则：
  - 解析 Markdown 相对链接 `[]()`
  - 忽略 `http/https/mailto/#/` 前缀
  - 校验去锚点后的本地路径是否存在

## 校验结果

- 失效链接数量：`0`
- 结果结论：文档相对链接可用率 `100%`

## 复现命令（PowerShell）

```powershell
$files=Get-ChildItem docs -Recurse -File -Filter *.md
$broken=@()
foreach($f in $files){
  $content=Get-Content $f.FullName -Raw
  $matches=[regex]::Matches($content,'\[[^\]]+\]\(([^)]+)\)')
  foreach($m in $matches){
    $target=$m.Groups[1].Value
    if($target -match '^(http|https|mailto|#|/)'){continue}
    if($target -match '^\s*$'){continue}
    $clean=$target.Split('#')[0]
    if($clean -eq ''){continue}
    $resolved=Join-Path $f.DirectoryName $clean
    if(-not (Test-Path $resolved)){
      $broken += [PSCustomObject]@{file=$f.FullName;link=$target}
    }
  }
}
"BROKEN_COUNT=$($broken.Count)"
$broken | Sort-Object file,link
```

## 备注

- 本报告聚焦“文件路径可达性”，不校验页面锚点是否存在。
- 站内运行时路由（如 `/api/docs/`）为系统 URL，不纳入文件路径校验。

