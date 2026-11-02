param([int]$k, [int]$n)
$data = 'C:\Users\aman.kumar\Coherent-Quadrant\data'
$arch = Get-ChildItem $data -Directory | Where-Object { $_.Name -match '_(stall|quota|noanswer|verify|captchas|reset|ratelimit|signin)_' -and $_.Name -notmatch '^ai_mode_batch_\d+(_chromium)?$' } | Sort-Object LastWriteTime
$i = 0
foreach ($d in $arch) {
  if (($i++ % $n) -ne $k) { continue }
  if ((Get-PSDrive C).Free -ge 22GB) { break }
  try { [System.IO.Directory]::Delete($d.FullName, $true) } catch { }
}
