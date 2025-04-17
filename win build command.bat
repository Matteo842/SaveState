@echo off
cls

echo =====================================
echo == SaveState Packaging Script ==
echo =====================================
echo.

:GET_TYPE
echo Select the package type:
echo   [F] One-File (.exe only, slower startup)
echo   [D] One-Folder (folder with .exe inside, faster startup)
echo.
set BuildType=
set /p BuildType="Enter F or D: "
rem Simple trim attempt
for /f "tokens=* delims= " %%a in ("%BuildType%") do set BuildType=%%a

set BUILD_COMMAND=
set BUILD_DESC=

if /i "%BuildType%"=="F" (
    set BUILD_COMMAND=pyinstaller --clean SaveState-OneFile.spec
    set BUILD_DESC=One-File (using SaveState-OneFile.spec)
    goto TYPE_OK
)
if /i "%BuildType%"=="D" (
    rem Usa il comando diretto da riga di comando per One-Dir perché funziona meglio del .spec
    set BUILD_COMMAND=pyinstaller --noconfirm --clean --onedir --name SaveState --windowed --icon="D:\SaveState\icon.ico" --add-data="icons;icons" --add-data="SaveState_en.qm;." --add-data="backup_runner.py;." --add-data="icon.png;." --hidden-import=PySide6.QtSvg --hidden-import=win32com.client --hidden-import=winshell --hidden-import=vdf --hidden-import=nbtlib SaveState_gui.py
    set BUILD_DESC=One-Folder (using command line arguments)
    goto TYPE_OK
)

rem Se non ha matchato né F né D
echo.
echo Invalid selection. Please enter only F or D.
echo.
goto GET_TYPE

:TYPE_OK
if "%BUILD_COMMAND%"=="" (
    echo ERROR: Internal script error - BUILD_COMMAND not set.
    goto END_SCRIPT
)

echo.
echo You selected: %BUILD_DESC%.
echo.
echo This script will execute the following command:
echo( & rem Use echo( to safely print potentially complex command
echo   %BUILD_COMMAND%
echo.
echo IMPORTANT NOTES:
echo * Ensure your Python code uses resource_path() correctly.
echo * Run this script from the main project directory.
echo.

:CONFIRM
set /p choice="Proceed with packaging? (Y/N): "
echo.

if /i "%choice%"=="Y" (
    rem Controlla esistenza spec file SOLO se stiamo facendo la build one-file
    if /i "%BuildType%"=="F" (
        if not exist "SaveState-OneFile.spec" (
            echo ERROR: The spec file 'SaveState-OneFile.spec' was not found!
            goto END_SCRIPT
        )
    )
    echo OK. Starting PyInstaller...
    echo Executing: %BUILD_COMMAND%
    echo.
    rem Esegui il comando memorizzato
    %BUILD_COMMAND%
    echo.
    echo PyInstaller process completed. Check the 'dist' folder.
) else if /i "%choice%"=="N" (
    echo Packaging cancelled by user.
) else (
    echo Invalid choice. Please enter Y or N.
    echo.
    goto CONFIRM
)

:END_SCRIPT
echo.
echo Press any key to close this window...
pause >nul
exit