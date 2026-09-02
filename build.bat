@echo off
REM ============================================================
REM  Budowanie DripSender do pojedynczego pliku .exe
REM  Wynik: dist\DripSender.exe
REM ============================================================
setlocal

echo [1/3] Instaluje zaleznosci...
py -3.13 -m pip install -r requirements.txt || goto :error

echo.
echo [2/3] Buduje aplikacje (to potrwa 1-2 minuty)...
py -3.13 -m PyInstaller ^
    --noconfirm ^
    --clean ^
    --onefile ^
    --windowed ^
    --name DripSender ^
    --icon assets\icon.ico ^
    --add-data "assets;assets" ^
    --collect-all customtkinter ^
    --collect-submodules keyring.backends ^
    --hidden-import keyring.backends.Windows ^
    --hidden-import win32ctypes.core ^
    --collect-submodules pystray ^
    --hidden-import pystray._win32 ^
    --hidden-import PIL._tkinter_finder ^
    --collect-submodules dns ^
    --hidden-import openpyxl ^
    main.py || goto :error

echo.
echo [3/3] Gotowe. Plik do przekazania klientowi:
echo     %CD%\dist\DripSender.exe
echo.
pause
exit /b 0

:error
echo.
echo !!! Budowanie nie powiodlo sie. Sprawdz komunikaty powyzej.
pause
exit /b 1
