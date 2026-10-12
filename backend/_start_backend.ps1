$out = 'D:\WCE\7th Sem\Major Project\NEW\GraphMind\backend\_server.log'
$err = 'D:\WCE\7th Sem\Major Project\NEW\GraphMind\backend\_server_err.log'
$py  = 'D:\WCE\7th Sem\Major Project\GraphMind\backend\venv\Scripts\python.exe'
$wd  = 'D:\WCE\7th Sem\Major Project\NEW\GraphMind\backend'
$p = Start-Process -FilePath $py `
    -ArgumentList '-m','uvicorn','api.main:app','--host','0.0.0.0','--port','8001' `
    -WorkingDirectory $wd `
    -WindowStyle Hidden `
    -RedirectStandardOutput $out `
    -RedirectStandardError $err `
    -PassThru
Write-Output ("PID=" + $p.Id)
