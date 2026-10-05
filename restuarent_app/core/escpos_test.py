# core/escpos_test.py

try:
    # pywin32 is Windows-only; this view must still be importable elsewhere so
    # the URLconf can load on a Linux CI runner.
    import win32print
except ImportError:  # pragma: no cover - non-Windows host
    win32print = None
from django.http import HttpResponse

def simple_win32print_test(request):
    """
    Django view that sends "Hello, World!" to the Windows printer named
    exactly as it appears under Control Panel → Devices and Printers.
    Always returns an HttpResponse so Django doesn’t complain.
    """
    if win32print is None:
        return HttpResponse(
            "Printing needs pywin32, which is only available on Windows.",
            status=501,
        )

    # 1) Change this to the exact name shown under Control Panel → Devices and Printers → Printer properties → General
    PRINTER_NAME = "KPOS_80 Printer"  # ← replace with your exact printer name

    try:
        # 2) Try to open a handle to that printer. If the name is wrong or offline,
        #    this will raise an exception.
        hPrinter = win32print.OpenPrinter(PRINTER_NAME)
    except Exception as e:
        error_msg = f"❌ Could not open printer '{PRINTER_NAME}': {e}"
        print(error_msg)  # Also print to console/log for debugging
        return HttpResponse(error_msg, status=500)

    try:
        # 3) Start a RAW print job (dataType="RAW" sends bytes exactly as given).
        job_info = ("Test Print Job", None, "RAW")
        hJob = win32print.StartDocPrinter(hPrinter, 1, job_info)
        win32print.StartPagePrinter(hPrinter)

        # 4) Build the raw bytes: "Hello, World!" + newline + blank lines.
        data = b"Hello, World!\r\n"
        data += b"\r\n\r\n\r\n"  # feed a few blank lines
        data += b"\r\n\r\n\r\n"
        
        #  • GS V 0  (full cut)
        data += b"\x1D\x56\x00"
        #
        #  • GS V 1  (partial cut)
        # data += b"\x1D\x56\x01"
        #
        #  • GS V B m  (full cut, older printers)
        # data += b"\x1D\x56\x42\x00"
        #
        #  • ESC i  (EPSON “cut and eject”)
        # data += b"\x1B\x69"
        #
        #  • ESC m  (another “cut” variation)
        # data += b"\x1B\x6D"

        # If your printer needs an explicit cut, uncomment one of these:
        # data += b"\x1D\x56\x42\x00"    # GS V B 0  (common full‐cut)
        # data += b"\x1B\x69"            # ESC i  (another cut command)

        # 5) Send the bytes to the printer
        win32print.WritePrinter(hPrinter, data)

        # 6) Finish the page and document
        win32print.EndPagePrinter(hPrinter)
        win32print.EndDocPrinter(hPrinter)

        success_msg = f"✅ Sent “Hello, World!” to the Windows printer '{PRINTER_NAME}'."
        print(success_msg)
        return HttpResponse(success_msg)
    except Exception as e:
        error_msg = f"❌ Error while printing: {e}"
        print(error_msg)
        return HttpResponse(error_msg, status=500)
    finally:
        # 7) Always close the printer handle
        win32print.ClosePrinter(hPrinter)
