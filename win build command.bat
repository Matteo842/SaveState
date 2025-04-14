@echo off
cls

echo ======================================
echo  Script per Pacchettizzare SaveState
echo ======================================
echo.
echo Questo script eseguira il seguente comando PyInstaller:
echo.
echo   pyinstaller --clean SaveState.spec
echo.
echo ATTENZIONE:
echo * Assicurati che il codice Python usi la funzione resource_path() per trovare le risorse incluse.
echo * Esegui questo script dalla cartella principale del progetto (dove si trova game_saver_gui.py).
echo.

set /p choice="Vuoi procedere con la pacchettizzazione? (S/N): "

echo.

if /i "%choice%"=="S" (
    echo OK. Avvio di PyInstaller in corso...
    echo.
    REM Esecuzione del comando PyInstaller
    pyinstaller --clean SaveState.spec
    echo.
    echo Processo di PyInstaller completato. Controlla la cartella 'dist'.
) else (
    echo Pacchettizzazione annullata dall'utente.
)

echo.
echo Premi un tasto per chiudere questa finestra...
pause >nul