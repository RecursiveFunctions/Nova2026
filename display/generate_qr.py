
import qrcode

# Demo QR code (not real authentication)
data = "NOVA-DEMO-ORDER-1042"

qr = qrcode.QRCode(
    version=1,
    box_size=10,
    border=4
)

qr.add_data(data)
qr.make(fit=True)

image = qr.make_image(
    fill_color="black",
    back_color="white"
)

image.save("display/order_qr.png")

print("QR code generated successfully!")
