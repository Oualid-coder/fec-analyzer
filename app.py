from fastapi import FastAPI, UploadFile, File
from fastapi.responses import FileResponse, HTMLResponse
import shutil, uuid, os
from main import run

app = FastAPI()

@app.get("/", response_class=HTMLResponse)
def index():
    return open("index.html").read()

@app.post("/analyser")
async def analyser(fec: UploadFile = File(...)):
    tmp = f"/tmp/{uuid.uuid4()}.xlsx"
    with open(tmp, "wb") as f:
        shutil.copyfileobj(fec.file, f)
    output = run(tmp)
    return FileResponse(output, filename="rapport_fec.xlsx",
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
