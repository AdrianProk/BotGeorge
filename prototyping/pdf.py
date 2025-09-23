from PyPDF2 import PdfReader, PdfWriter

def reverse_pdf(input_pdf, output_pdf):
    reader = PdfReader(input_pdf)
    writer = PdfWriter()

    for page in reversed(reader.pages):
        writer.add_page(page)

    with open(output_pdf, "wb") as output_file:
        writer.write(output_file)

# Beispielaufruf
input = "input.pdf"
output = "output.pdf"

reverse_pdf(input, output)
