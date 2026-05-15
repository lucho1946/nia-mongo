# ============================================================
# routers/uploads.py
# Responsabilidad única:
# - recibir archivos desde el frontend
# - guardarlos en disco
# - devolver metadata lista para NIA
# ============================================================

from fastapi import APIRouter, UploadFile, File, HTTPException
from pathlib import Path
from uuid import uuid4
import shutil

router = APIRouter(tags=["Uploads"])

# Carpeta donde se guardarán los archivos subidos
UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


def detectar_tipo_por_extension(nombre_archivo: str, mimetype: str | None = None) -> str:
    """
    Detecta el tipo de archivo para NIA.
    """
    ext = Path(nombre_archivo).suffix.lower().lstrip(".")

    if mimetype and mimetype.startswith("image/"):
        return "imagen"

    if mimetype == "application/pdf" or ext == "pdf":
        return "pdf"

    if ext in {"doc", "docx", "txt", "rtf", "odt", "xls", "xlsx", "csv"}:
        return "documento"

    if ext in {"jpg", "jpeg", "png", "webp", "bmp", "tif", "tiff"}:
        return "imagen"

    return "otro"


@router.post("/upload-archivo")
async def upload_archivo(archivo: UploadFile = File(...)):
    """
    Recibe un archivo, lo guarda en la carpeta uploads/
    y devuelve la metadata necesaria para NIA.
    """
    if not archivo.filename:
        raise HTTPException(status_code=400, detail="El archivo no tiene nombre válido.")

    nombre_original = Path(archivo.filename).name
    extension = Path(nombre_original).suffix.lower()
    nombre_guardado = f"{uuid4().hex}{extension}"
    ruta_guardado = UPLOAD_DIR / nombre_guardado

    try:
        with ruta_guardado.open("wb") as buffer:
            shutil.copyfileobj(archivo.file, buffer)

        archivo_tipo = detectar_tipo_por_extension(
            nombre_original,
            archivo.content_type
        )

        return {
            "ok": True,
            "archivo_nombre": nombre_original,
            "archivo_tipo": archivo_tipo,
            "archivo_ruta": str(ruta_guardado.as_posix()),
            "archivo_mimetype": archivo.content_type or "application/octet-stream",
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error guardando archivo: {e}"
        )