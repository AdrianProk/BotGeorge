
import segno
from urllib.request import urlopen
from tkinter import *



#QR code Gerneration 

def generateQR():
    slts_qrcode = segno.make_qr("lol")
    backgound_url = urlopen("https://i.pinimg.com/originals/a6/38/b2/a638b205b472d66ad408ab6d53bab808.png")
    #to_artistic is part of some qr_to_artistic or some shit. you need to google it
    slts_qrcode.to_artistic(  
        background=backgound_url,
        target="testqr.png",
        scale=10,
    )
    

# Window
fenster = Tk()

fenster.title("QR code Generator")

generateQR()
img = PhotoImage(file="testqr.png")

fenster.geometry("800x800")

canvas = Canvas(fenster, width = 500, height = 500)
canvas.pack()

text = Text(fenster, height= 100, width= 50)

canvas.create_image(20,20, anchor=NW, image=img)



text.insert("1.0", "This is your QR code")
text.pack()
fenster.mainloop()