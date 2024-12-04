# ddrcv

# Connecting to OBS from Pi

Make Ethernet-to-USB a private connection
```
Get-NetConnectionProfile
Set-NetConnectionProfile -InterfaceIndex <InterfaceIndex> -NetworkCategory Private
```

May not need to do this:
```
netsh advfirewall firewall add rule name="Allow Port 4455" dir=in action=allow protocol=TCP localport=4455 remoteip=Any
```