' StreamDesk startup launcher — runs pythonw as admin, hidden
Set oShell = CreateObject("WScript.Shell")
strDir = Left(WScript.ScriptFullName, InStrRev(WScript.ScriptFullName, "\"))
strScript = strDir & "streamdesk.py"

' Find pythonw.exe (runs without a console window)
Dim pyExe
pyExe = ""

' Try common locations
Dim candidates(4)
candidates(0) = "C:\Program Files\Python313\pythonw.exe"
candidates(1) = "C:\Program Files\Python312\pythonw.exe"
candidates(2) = "C:\Program Files\Python311\pythonw.exe"
candidates(3) = "C:\Program Files\Python310\pythonw.exe"
candidates(4) = "C:\Users\" & CreateObject("WScript.Network").UserName & "\AppData\Local\Programs\Python\Python313\pythonw.exe"

Dim fso
Set fso = CreateObject("Scripting.FileSystemObject")
Dim i
For i = 0 To 4
    If fso.FileExists(candidates(i)) Then
        pyExe = candidates(i)
        Exit For
    End If
Next

' Fall back to python in PATH
If pyExe = "" Then pyExe = "pythonw.exe"

' Launch with admin elevation, hidden window
oShell.Run Chr(34) & pyExe & Chr(34) & " " & Chr(34) & strScript & Chr(34) & " --tray", 0, False
