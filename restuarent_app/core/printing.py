try:
    # pywin32 is Windows-only. The rest of the app must still import on other
    # platforms (Linux CI runners, a Linux server) - printing simply becomes a
    # no-op there instead of crashing at import time.
    import win32print
except ImportError:  # pragma: no cover - non-Windows host
    win32print = None

# Default fallback printer
DEFAULT_PRINTER_NAME = "POS80 Printer"

def send_to_printer(raw_bytes: bytes, printer_name: str = None) -> None:
    """
    Open the Windows printer handle, send `raw_bytes` as a RAW job.
    Uses `printer_name` if provided, otherwise uses DEFAULT_PRINTER_NAME.
    """
    # 1. Use the specific name provided, otherwise fallback to default
    target_printer = printer_name if printer_name else DEFAULT_PRINTER_NAME

    # Debugging: check your console to see which printer is being targeted
    print(f"DEBUG: Attempting to print to: {target_printer}") 

    if win32print is None:
        # Never fail the surrounding request because a host has no printer stack.
        print(f"PRINTER SKIP on {target_printer}: pywin32 is unavailable on this platform")
        return

    try:
        hprinter = win32print.OpenPrinter(target_printer)
        try:
            job_info = ("POS Print Job", None, "RAW")
            hjob = win32print.StartDocPrinter(hprinter, 1, job_info)
            win32print.StartPagePrinter(hprinter)
            win32print.WritePrinter(hprinter, raw_bytes)
            win32print.EndPagePrinter(hprinter)
            win32print.EndDocPrinter(hprinter)
        finally:
            win32print.ClosePrinter(hprinter)

    except Exception as e:
        print(f"CRITICAL PRINTER ERROR on {target_printer}: {e}")
        # We catch the error so the order still saves even if print fails



def build_market_list_bytes(items):
    """
    Generates ESC/POS bytes for a simple shopping/market list.
    items: list of dicts [{'name': 'Tomato', 'qty': 5, 'unit': 'kg'}, ...]
    """
    ESC = b"\x1B"
    GS  = b"\x1D"
    lines = []

    # 1. Header
    lines.append(ESC + b"\x40")          # Initialize
    lines.append(ESC + b"\x61" + b"\x01") # Center
    lines.append(ESC + b"\x21" + b"\x20") # Double Width
    lines.append(b"ORDER LIST\n")
    lines.append(ESC + b"\x21" + b"\x00") # Normal text
    lines.append(b"\n")
    
    # 2. Date
    from django.utils import timezone
    now = timezone.localtime(timezone.now()).strftime("%Y-%m-%d %I:%M %p")
    lines.append(ESC + b"\x61" + b"\x00") # Left align
    lines.append(f"Date: {now}\n".encode('ascii'))
    lines.append(b"-" * 32 + b"\n")

    # 3. Columns
    # Item (Left) | Qty (Right)
    lines.append(ESC + b"\x45" + b"\x01") # Bold ON
    lines.append(b"Item                    Qty\n")
    lines.append(ESC + b"\x45" + b"\x00") # Bold OFF
    lines.append(b"-" * 32 + b"\n")

    # 4. Items Loop
    for it in items:
        name = it.get('name', 'Unknown')[:20] # Truncate name
        qty = str(it.get('qty', 0))
        unit = it.get('unit', '')
        
        # Format: Name (left 20) + Qty/Unit (right rest)
        qty_str = f"{qty} {unit}"
        
        name_bytes = name.ljust(20).encode('ascii', 'ignore')
        qty_bytes = qty_str.rjust(11).encode('ascii', 'ignore') # 32 - 1 (space) - 20 = 11 approx
        
        lines.append(name_bytes + b" " + qty_bytes + b"\n")
        lines.append(b"................................\n") # Optional dotted line separator

    lines.append(b"\n\n\n\n")
    
    # 5. Cut
    lines.append(GS + b"\x56" + b"\x00")
    
    return b"".join(lines)