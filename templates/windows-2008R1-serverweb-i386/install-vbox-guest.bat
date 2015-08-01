if exist e:\cert\VBoxCertUtil (
   cmd /c e:\cert\VBoxCertUtil add-trusted-publisher e:\cert\oracle-vbox.cer --root e:\cert\oracle-vbox.cer
) else (
   cmd /c certutil -addstore -f "TrustedPublisher" a:oracle-cert.cer
)
cmd /c e:\VBoxWindowsAdditions-x86.exe /S
cmd /c shutdown.exe /r /t 5 /d p:2:4 /c "Vagrant reboot for VBoxWindowsAdditions"
