# core/escpos_printers.py

try:
    # pywin32 is Windows-only. These helpers must stay importable on other
    # platforms (Linux CI runners, a Linux server); the print functions below
    # become no-ops there rather than raising at import time.
    import win32print
    import win32ui
except ImportError:  # pragma: no cover - non-Windows host
    win32print = None
    win32ui = None
from django.conf import settings
from django.utils.timezone import localtime
from django.templatetags.static import static
from PIL import Image

# ──────────────────────────────────────────────────────────────
# Adjust these exactly to match what your Control Panel → Devices
# and Printers → [Your Printer] shows under “Name.” For a single
# printer, you can just use PRINTER_NAME for both token and bill.
# ──────────────────────────────────────────────────────────────
TOKEN_PRINTER_NAME = "KPOS_80 Kitchen"    # e.g. your kitchen‐slip printer
BILL_PRINTER_NAME  = "KPOS_80 Billing"    # e.g. your bill/invoice printer

def _open_printer_handle(printer_name):
    """
    Try to open a handle to the given Windows printer name.
    Raises exception if the name is invalid or printer offline.
    """
    try:
        handle = win32print.OpenPrinter(printer_name)
        return handle
    except Exception as e:
        raise RuntimeError(f"Could not open printer '{printer_name}': {e}")

def _end_doc_and_close(hPrinter):
    """
    Called after starting a Doc + Page. Ends and closes the handle.
    """
    try:
        win32print.EndPagePrinter(hPrinter)
        win32print.EndDocPrinter(hPrinter)
    finally:
        win32print.ClosePrinter(hPrinter)

def print_token(order):
    """
    Builds and sends ESC/POS bytes to the TOKEN_PRINTER_NAME printer.
    The “token” slip usually just shows: Restaurant name (large), logo (if any),
    “Token #1234” in huge font, date/time, and item list (just names + qty),
    then a cut.
    """
    if win32print is None:
        print("PRINTER SKIP print_token: pywin32 is unavailable on this platform")
        return None

    # 1) Open printer handle
    hPrinter = _open_printer_handle(TOKEN_PRINTER_NAME)

    try:
        # 2) Start a RAW print job
        job_info = (f"Token Order #{order.number}", None, "RAW")
        hJob = win32print.StartDocPrinter(hPrinter, 1, job_info)
        win32print.StartPagePrinter(hPrinter)

        # 3) Build raw ESC/POS commands:

        # ─── Basic helper to center‐align vs left‐align vs big text ───
        ESC = b"\x1B"
        GS  = b"\x1D"

        data = b""

        # (a) Center‐align, print restaurant name in double height+width
        data += ESC + b"\x61" + b"\x01"           # ESC a 1  → center
        data += ESC + b"\x21" + b"\x30"           # ESC ! 0x30 → double‐height+width
        rest_name = settings.RESTAURANT_NAME.encode("ascii", "replace")
        data += rest_name + b"\n"
        data += ESC + b"\x21" + b"\x00"           # ESC ! 0  → back to normal

        # (b) If you have a logo file (BMP/PNG), you can convert to ESC/POS image here.
        #     For simplicity, we skip logo or assume not supported. If you do want it:
        #     1. Use PIL to open the static logo, convert to monochrome, then use win32ui to send.
        #
        # Example (uncomment if you want):
        # try:
        #     bmp = Image.open(settings.LOGO_PATH)  # e.g. absolute path to "base_static/img/logo.png"
        #     hDC = win32ui.CreateDC()
        #     hDC.CreatePrinterDC(TOKEN_PRINTER_NAME)
        #     dib = win32ui.CreateBitmap()
        #     dib.CreateCompatibleBitmap(hDC, bmp.width, bmp.height)
        #     hDC.SelectObject(dib)
        #     hDC.DrawImage(bmp)
        #     win32print.WritePrinter(hPrinter, dib.GetBitmapBits(True))
        # except Exception:
        #     pass

        # (c) A blank line, then print “Token #<number>” in very large font:
        data += b"\n"
        data += ESC + b"\x21" + b"\x20"           # ESC ! 0x20 → double‐height only (or 0x30 for double‐both)
        token_line = f"Token # {order.token_number}".encode("ascii", "replace") + b"\n"
        data += token_line
        data += ESC + b"\x21" + b"\x00"           # back to normal

        # (d) Print date/time:
        dt = localtime(order.created_at).strftime("%Y-%m-%d %H:%M")
        data += ESC + b"\x61" + b"\x00"           # ESC a 0 → left‐align
        data += f"Date: {dt}\n".encode("ascii", "replace")

        # (e) Separator
        data += b"------------------------------\n"

        # (f) List each item (name × qty), one per line:
        for item in order.items.all():
            if item.menu_item_id:
                name = item.menu_item.name
            else:
                name = item.deal.name
            line = f"{name}  x{item.quantity}\n"
            data += line.encode("ascii", "replace")

        data += b"\n\n\n"

        # (g) Finally, send a full‐cut command:
        data += GS + b"\x56" + b"\x00"       # GS V 0  → full cut

        # 4) Send it:
        win32print.WritePrinter(hPrinter, data)

    finally:
        _end_doc_and_close(hPrinter)


def print_bill(order):
    """
    Builds and sends ESC/POS bytes to the BILL_PRINTER_NAME printer. 
    The bill/invoice slip typically shows:
      • Restaurant name (+ optional small logo)
      • Invoice header: Order #, Date/Time, Token #
      • A table of items: Name | Qty | Unit ₹ | Total ₹
      • Subtotal, Discount, Tax, Service Charge, Grand Total 
      • Footer: “Powered by Qonkar Technologies – Contact: …”
      • Finally cut.
    """
    if win32print is None:
        print("PRINTER SKIP print_bill: pywin32 is unavailable on this platform")
        return None

    hPrinter = _open_printer_handle(BILL_PRINTER_NAME)

    try:
        job_info = (f"Bill Order #{order.number}", None, "RAW")
        hJob = win32print.StartDocPrinter(hPrinter, 1, job_info)
        win32print.StartPagePrinter(hPrinter)

        ESC = b"\x1B"
        GS  = b"\x1D"
        data = b""

        # (1) Center + bold header for restaurant
        data += ESC + b"\x61" + b"\x01"  # center
        data += ESC + b"\x21" + b"\x10"  # ESC ! 0x10 → double‐height
        rest_name = settings.RESTAURANT_NAME.encode("ascii", "replace")
        data += rest_name + b"\n"
        data += ESC + b"\x21" + b"\x00"  # back to normal

        # (2) Maybe a tiny logo:
        #  [You can embed a small 1‐bit BMP here if desired, similar to above.]

        data += b"\n"
        data += ESC + b"\x61" + b"\x00"  # left align
        # (3) Invoice header
        dt = localtime(order.created_at).strftime("%Y-%m-%d %H:%M")
        data += f"Order #: {order.number}\n".encode("ascii", "replace")
        data += f"Token #: {order.token_number}\n".encode("ascii", "replace")
        data += f"Date: {dt}\n".encode("ascii", "replace")
        data += b"------------------------------\n"

        # (4) Items header (Name      Qty   Unit    Total)
        header = "Item               QTY  Unit   Total\n"
        data += header.encode("ascii", "replace")
        data += b"------------------------------\n"

        # (5) For each OrderItem, show a formatted row:
        for item in order.items.all():
            if item.menu_item_id:
                name = item.menu_item.name
            else:
                name = item.deal.name
            qty = item.quantity
            unit = f"{item.unit_price:.2f}"
            line_total = item.quantity * float(item.unit_price)
            total_str = f"{line_total:.2f}"

            # Pad/truncate name to 15 chars, right‐align numbers in fixed columns
            name_field = name[:15].ljust(15)
            qty_field  = str(qty).rjust(3)
            unit_field = unit.rjust(7)
            total_field= total_str.rjust(7)
            row = f"{name_field}{qty_field}{unit_field}{total_field}\n"
            data += row.encode("ascii", "replace")

        data += b"------------------------------\n"

        # (6) Totals
        # Modifiers are charged per unit and each order can carry several taxes,
        # so the totals are taken from the order model rather than recomputed here.
        subtotal = float(order.get_subtotal())
        discount = float(order.discount or 0)
        service_charge = float(order.service_charge or 0)
        grand_total = float(order.get_total())
        tax_lines = order.tax_display_lines()

        data += f"Subtotal:       ₹{subtotal:,.2f}\n".encode("ascii", "replace")
        data += f"Discount:       ₹{discount:,.2f}\n".encode("ascii", "replace")
        for tax_line in tax_lines:
            if tax_line.tax_type == 'fixed':
                tax_label = f"{tax_line.name} (fixed)"
            else:
                tax_label = f"{tax_line.name} ({float(tax_line.rate or 0):g}%)"
            data += (f"{tax_label + ':':<16}₹{float(tax_line.amount):,.2f}\n").encode("ascii", "replace")
        data += f"Service:        ₹{service_charge:,.2f}\n".encode("ascii", "replace")
        data += b"------------------------------\n"
        data += f"Grand Total:    ₹{grand_total:,.2f}\n".encode("ascii", "replace")
        data += b"\n"

        # (7) Footer / signature
        footer = "Powered by Qonkar Technologies\nContact: +1-234-567-890\n"
        data += ESC + b"\x61" + b"\x01"  # center
        data += footer.encode("ascii", "replace")
        data += ESC + b"\x61" + b"\x00"  # back to left

        data += b"\n\n\n"
        data += GS + b"\x56" + b"\x00"  # full cut

        win32print.WritePrinter(hPrinter, data)

    finally:
        _end_doc_and_close(hPrinter)
