' run_hidden.vbs

' StreamDesk startup launcher — runs pythonw as admin, hidden
' Uses ShellExecute with "runas" verb so UAC grants admin rights.

Dim oShell, fso, strDir, strScript, pyExe
Set oShell = CreateObject("WScript.Shell")
Set fso    = CreateObject("Scripting.FileSystemObject")

strDir    = Left(WScript.ScriptFullName, InStrRev(WScript.ScriptFullName, "\"))
strScript = strDir & "streamdesk.py"

' ---- Locate pythonw.exe ----
Dim candidates(6)
candidates(0) = "C:\Program Files\Python313\pythonw.exe"
candidates(1) = "C:\Program Files\Python312\pythonw.exe"
candidates(2) = "C:\Program Files\Python311\pythonw.exe"
candidates(3) = "C:\Program Files\Python310\pythonw.exe"
candidates(4) = "C:\Program Files\Python39\pythonw.exe"
candidates(5) = "C:\Users\" & CreateObject("WScript.Network").UserName & "\AppData\Local\Programs\Python\Python313\pythonw.exe"
candidates(6) = "C:\Users\" & CreateObject("WScript.Network").UserName & "\AppData\Local\Programs\Python\Python312\pythonw.exe"

pyExe = ""
Dim i
For i = 0 To 6
    If fso.FileExists(candidates(i)) Then
        pyExe = candidates(i)
        Exit For
    End If
Next

' Fall back: ask the shell to find it in PATH
If pyExe = "" Then
    On Error Resume Next
    pyExe = oShell.Exec("cmd /c where pythonw.exe").StdOut.ReadLine()
    On Error GoTo 0
    If Not fso.FileExists(pyExe) Then pyExe = "pythonw.exe"
End If

' ---- Launch elevated + hidden via ShellExecute ----
' ShellExecute with "runas" triggers UAC and grants admin token.
' Window style 0 = hidden; bWaitOnReturn = False.
Dim oWsh
Set oWsh = CreateObject("Shell.Application")
oWsh.ShellExecute pyExe, Chr(34) & strScript & Chr(34) & " --tray", strDir, "runas", 0