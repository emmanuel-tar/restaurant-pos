# core/escpos_utils.py

from escpos.printer import Usb, Serial, Network, CUPS, Dummy
from django.conf import settings

# ------------------------------------------------------------
# 1) Pick the correct Printer class for your environment:
#
#    * If your printer is a USB ESC/POS device, use Usb(...)
#    * If it is Serial (e.g. /dev/ttyUSB0), use Serial(...)
#    * If it is networked (TCP/IP at IP 192.168.0.100:9100), use Network(...)
#    * If you simply want to hand off to CUPS, use CUPS(...)
#
#    You only need to uncomment the block that matches your setup.
# ------------------------------------------------------------

# === A) USB ESC/POS example ===
#   Change VENDOR_ID and PRODUCT_ID to match your printer's values.
#   To find them on Linux: lsusb → e.g. 0x04b8:0x0202 (EPSON)
#   On Windows: check Device Manager → USB → “Hardware Ids.”
USB_VENDOR_ID = 0x04b8      # ← replace with your printer’s vendor ID (hex)
USB_PRODUCT_ID = 0x0202     # ← replace with your printer’s product ID (hex)
USB_INTERFACE = 0           # often 0, but sometimes 1
# printer = Usb(USB_VENDOR_ID, USB_PRODUCT_ID, interface=USB_INTERFACE)

# === B) Serial ESC/POS example ===
#   /dev/ttyUSB0 or COM3 or similar. Baudrate = 19200 (common), 8 data bits, no parity.
# SERIAL_PORT = "/dev/ttyUSB0"  # or "COM3" on Windows
# SERIAL_BAUDRATE = 19200
# printer = Serial(devfile=SERIAL_PORT, baudrate=SERIAL_BAUDRATE, bytesize=8, parity='N', stopbits=1, timeout=1.00)

# === C) Network ESC/POS example ===
#   If your printer is reachable on 192.168.0.100 at port 9100
# PRINTER_IP = "192.168.0.100"
# PRINTER_PORT = 9100
# printer = Network(PRINTER_IP, PRINTER_PORT)

# === D) CUPS example (Linux/macOS) ===
#   If your printer is installed under CUPS as “EPSON_TM-T20II”
# CUPS_PRINTER_NAME = "EPSON_TM-T20II"
# printer = CUPS(CUPS_PRINTER_NAME)

# === E) Dummy (for testing: doesn’t actually print) ===
# printer = Dummy()

# ------------------------------------------------------------
# 2) Helper function to return your chosen printer instance
# ------------------------------------------------------------
def get_printer():
    """
    Return a configured ESC/POS printer object.
    Uncomment the one that matches your physical connection.
    """
    # USB example:
    return Usb(USB_VENDOR_ID, USB_PRODUCT_ID, interface=USB_INTERFACE)

    # Serial example:
    # return Serial(devfile=SERIAL_PORT, baudrate=SERIAL_BAUDRATE, bytesize=8, parity='N', stopbits=1, timeout=1.00)

    # Network example:
    # return Network(PRINTER_IP, PRINTER_PORT)

    # CUPS example:
    # return CUPS(CUPS_PRINTER_NAME)

    # Dummy (no‐op):
    # return Dummy()

# ------------------------------------------------------------
# 3) Print the Token (simple “Token # 123”) with ESC/POS
# ------------------------------------------------------------
def print_token(order):
    p = get_printer()
    try:
        p.set(align="center", text_type="B", width=2, height=2)  # Double‐wide, double‐tall header
        p.text("***** TOKEN *****\n")
        p.set(align="center", text_type="NORMAL", width=1, height=1)
        p.text(f"Token #: {order.token_number}\n")
        p.text(f"Order  #: {order.number}\n")
        p.text("------------------------------\n")
        p.text("\n\n\n")   # feed some lines, then cut
        p.cut()
    except Exception as e:
        # Log or handle errors here. For simplicity, re‐raise.
        raise

# ------------------------------------------------------------
# 4) Print the Bill (Itemized) with ESC/POS
# ------------------------------------------------------------
def print_bill(order):
    """
    This prints a simple table:

    Item         QTY   Unit   Total
    -------      ---   ----   -----
    Burger        2    50.00   100.00
    Fries         1    30.00    30.00

    Then:
    Subtotal: 130.00
    Discount:  0.00
    Tax (5%):   6.50
    Service:    5.00
    ---------------------
    Grand Total: 141.50
    """

    p = get_printer()
    try:
        p.set(align="center", text_type="B", width=2, height=2)
        p.text("***** INVOICE *****\n")
        p.set(align="center", text_type="NORMAL", width=1, height=1)
        p.text(f"Order #: {order.number}\n")
        p.text(f"Date   : {order.created_at.strftime('%Y-%m-%d %H:%M')}\n")
        p.text(f"Token  : {order.token_number}\n")
        p.text("------------------------------\n")
        p.set(align="left")

        # Header row
        p.text(f"{'Item':<12}{'QTY':>4}{'Unit':>8}{'Total':>8}\n")
        p.text("--------------------------------\n")

        # For each OrderItem, calculate line total
        for oi in order.items.all():
            if oi.menu_item:
                name = oi.menu_item.name[:12]
            else:
                name = oi.deal.name[:12]

            qty = oi.quantity
            unit = f"{oi.unit_price:.2f}"
            line_total = oi.quantity * oi.unit_price
            total_str = f"{line_total:.2f}"

            p.text(f"{name:<12}{qty:>4}{unit:>8}{total_str:>8}\n")

        p.text("--------------------------------\n")

        # Subtotal is annotated on the order (assuming you did that in OrderListView)
        subtotal = float(order.get_subtotal())

        discount = float(order.discount or 0)
        service = float(order.service_charge or 0)

        grand_total = float(order.get_total())

        p.text(f"{'Subtotal:':<20}{subtotal:>10.2f}\n")
        p.text(f"{'Discount:':<20}{discount:>10.2f}\n")
        for tax_line in order.tax_display_lines():
            if tax_line.tax_type == 'fixed':
                tax_label = f"{tax_line.name} (fixed)"
            else:
                tax_label = f"{tax_line.name} ({float(tax_line.rate or 0):g}%)"
            p.text(f"{tax_label + ':':<20}{float(tax_line.amount):>10.2f}\n")
        p.text(f"{'Service:':<20}{service:>10.2f}\n")
        p.text("--------------------------------\n")
        p.set(align="left", text_type="B")
        p.text(f"{'Grand Total:':<20}{grand_total:>10.2f}\n")

        p.text("\n\n")   # feed
        p.cut()
    except Exception as e:
        raise
