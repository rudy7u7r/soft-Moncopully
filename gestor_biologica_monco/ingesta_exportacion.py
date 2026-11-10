import csv
import io
import zipfile
from datetime import date, datetime, timedelta
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

from django.core.exceptions import ValidationError

from .models import Bovino, Madre, PajuelaSemen, Parentesco, Raza


def generar_xlsx_bytes(nombre_hoja, encabezados, filas):
    """
    Genera un archivo Excel (.xlsx OpenXML estándar) en memoria sin dependencias externas.
    Compatible con Microsoft Excel, LibreOffice Calc y Google Sheets.
    """
    buffer = io.BytesIO()

    def col_letter(idx):
        result = ""
        n = idx + 1
        while n > 0:
            n, rem = divmod(n - 1, 26)
            result = chr(65 + rem) + result
        return result

    sheet_rows_xml = []
    todas_las_filas = [encabezados] + list(filas)

    for r_idx, fila in enumerate(todas_las_filas, start=1):
        celdas_xml = []
        estilo = ' s="1"' if r_idx == 1 else ' s="0"'
        for c_idx, valor in enumerate(fila):
            ref = f"{col_letter(c_idx)}{r_idx}"
            if valor is None:
                valor_str = ""
            else:
                valor_str = str(valor)

            # Si no es encabezado y es numérico puro, escribir como número
            if r_idx > 1 and isinstance(valor, (int, float)) and not isinstance(valor, bool):
                celdas_xml.append(f'<c r="{ref}"{estilo}><v>{valor}</v></c>')
            else:
                texto_escapado = escape(valor_str)
                celdas_xml.append(
                    f'<c r="{ref}" t="inlineStr"{estilo}><is><t>{texto_escapado}</t></is></c>'
                )
        sheet_rows_xml.append(f'<row r="{r_idx}">{"".join(celdas_xml)}</row>')

    sheet_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<sheetData>{"".join(sheet_rows_xml)}</sheetData>'
        '</worksheet>'
    )

    nombre_limpio = escape((nombre_hoja or "Datos")[:31])

    workbook_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f'<sheets><sheet name="{nombre_limpio}" sheetId="1" r:id="rId1"/></sheets>'
        '</workbook>'
    )

    styles_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<fonts count="2">'
        '<font><sz val="11"/><color rgb="FF1F2D24"/><name val="Calibri"/></font>'
        '<font><b/><sz val="11"/><color rgb="FFFFFFFF"/><name val="Calibri"/></font>'
        '</fonts>'
        '<fills count="3">'
        '<fill><patternFill patternType="none"/></fill>'
        '<fill><patternFill patternType="gray125"/></fill>'
        '<fill><patternFill patternType="solid"><fgColor rgb="FF0F4A29"/><bgColor indexed="64"/></patternFill></fill>'
        '</fills>'
        '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
        '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
        '<cellXfs count="2">'
        '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
        '<xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1"/>'
        '</cellXfs>'
        '</styleSheet>'
    )

    content_types_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
        '</Types>'
    )

    rels_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
        '</Relationships>'
    )

    workbook_rels_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
        '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
        '</Relationships>'
    )

    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types_xml)
        zf.writestr("_rels/.rels", rels_xml)
        zf.writestr("xl/workbook.xml", workbook_xml)
        zf.writestr("xl/_rels/workbook.xml.rels", workbook_rels_xml)
        zf.writestr("xl/styles.xml", styles_xml)
        zf.writestr("xl/worksheets/sheet1.xml", sheet_xml)

    buffer.seek(0)
    return buffer.getvalue()


def _leer_filas_desde_xlsx(raw_bytes):
    """Extrae las filas de la primera hoja de un archivo .xlsx."""
    with zipfile.ZipFile(io.BytesIO(raw_bytes), mode="r") as zf:
        ns = {"main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        shared_strings = []
        if "xl/sharedStrings.xml" in zf.namelist():
            ss_root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
            for si in ss_root.findall("main:si", ns):
                textos = [t.text or "" for t in si.findall(".//main:t", ns)]
                shared_strings.append("".join(textos))

        sheet_name = "xl/worksheets/sheet1.xml"
        if sheet_name not in zf.namelist():
            hojas = [n for n in zf.namelist() if n.startswith("xl/worksheets/sheet") and n.endswith(".xml")]
            if not hojas:
                raise ValueError("El archivo Excel no contiene hojas de cálculo válidas.")
            sheet_name = sorted(hojas)[0]

        sheet_root = ET.fromstring(zf.read(sheet_name))
        filas = []

        def col_to_idx(cell_ref):
            letras = "".join(ch for ch in cell_ref if ch.isalpha()).upper()
            idx = 0
            for ch in letras:
                idx = idx * 26 + (ord(ch) - 64)
            return max(0, idx - 1)

        for row_el in sheet_root.findall(".//main:sheetData/main:row", ns):
            valores_fila = {}
            max_col = -1
            for c_el in row_el.findall("main:c", ns):
                ref = c_el.attrib.get("r", "A1")
                c_idx = col_to_idx(ref)
                max_col = max(max_col, c_idx)
                c_type = c_el.attrib.get("t", "")
                val_str = ""
                if c_type == "s":
                    v_el = c_el.find("main:v", ns)
                    if v_el is not None and v_el.text is not None:
                        s_idx = int(v_el.text)
                        if 0 <= s_idx < len(shared_strings):
                            val_str = shared_strings[s_idx]
                elif c_type == "inlineStr":
                    t_els = c_el.findall(".//main:t", ns)
                    val_str = "".join(t.text or "" for t in t_els)
                else:
                    v_el = c_el.find("main:v", ns)
                    if v_el is not None and v_el.text is not None:
                        val_str = v_el.text
                valores_fila[c_idx] = (val_str or "").strip()

            if max_col >= 0:
                fila_lista = [valores_fila.get(i, "") for i in range(max_col + 1)]
                if any(celda != "" for celda in fila_lista):
                    filas.append(fila_lista)

        return filas


def _leer_filas_desde_csv(raw_bytes):
    """Extrae las filas desde un archivo CSV detectando codificación y delimitador."""
    texto = None
    for enc in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            texto = raw_bytes.decode(enc)
            break
        except UnicodeDecodeError:
            continue

    if texto is None:
        raise ValueError("No fue posible decodificar el archivo CSV. Use codificación UTF-8 o Latin-1.")

    muestra = texto[:2048]
    delimitador = ";" if muestra.count(";") > muestra.count(",") else ","
    lector = csv.reader(io.StringIO(texto), delimiter=delimitador)
    filas = []
    for fila in lector:
        fila_limpia = [(c or "").strip() for c in fila]
        if any(celda != "" for celda in fila_limpia):
            filas.append(fila_limpia)
    return filas


def _parsear_fecha(valor_fecha):
    """Convierte distintos formatos de fecha (o serie Excel) a datetime.date."""
    val = (valor_fecha or "").strip()
    if not val:
        raise ValueError("La fecha de nacimiento está vacía.")

    # Si proviene de un número serial de Excel (ej. 44562)
    if val.isdigit() and 20000 <= int(val) <= 60000:
        base_excel = date(1899, 12, 30)
        return base_excel + timedelta(days=int(val))

    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(val, fmt).date()
        except ValueError:
            continue

    raise ValueError(f"Formato de fecha inválido '{val}'. Use AAAA-MM-DD o DD/MM/AAAA.")


def _normalizar_sexo(valor_sexo):
    val = (valor_sexo or "").strip().lower()
    if val in ("hembra", "vaca", "f", "h", "vaquilla"):
        return "Hembra"
    if val in ("macho", "toro", "m", "novillo", "ternero macho"):
        return "Macho"
    raise ValueError(f"Clasificación de sexo inválida '{valor_sexo}'. Use 'Hembra' o 'Macho'.")


def procesar_ingesta_rfid(archivo_subido, modo_duplicados="omitir"):
    """
    Procesa y valida un archivo CSV o Excel (.xlsx) de registros RFID con bloques try-except.
    Retorna un diccionario con estadísticas y el detalle fila por fila.
    """
    reporte = {
        "nombre_archivo": getattr(archivo_subido, "name", "archivo"),
        "total_filas": 0,
        "creados": 0,
        "actualizados": 0,
        "omitidos": 0,
        "errores": 0,
        "error_general": None,
        "detalles": [],
    }

    try:
        nombre_lower = reporte["nombre_archivo"].lower()
        raw_bytes = archivo_subido.read()
        if not raw_bytes:
            raise ValidationError("El archivo seleccionado está vacío.")

        if nombre_lower.endswith(".xlsx"):
            filas = _leer_filas_desde_xlsx(raw_bytes)
        elif nombre_lower.endswith(".csv") or nombre_lower.endswith(".txt"):
            filas = _leer_filas_desde_csv(raw_bytes)
        else:
            raise ValidationError("Formato no soportado. Suba un archivo .csv o .xlsx.")

        if len(filas) < 2:
            raise ValidationError("El archivo debe contener una fila de encabezados y al menos una fila de datos.")

        # Mapear encabezados de forma flexible
        encabezados_raw = [h.strip().lower().replace(" ", "_") for h in filas[0]]
        mapa_col = {}
        for idx, nombre_col in enumerate(encabezados_raw):
            if "rfid" in nombre_col or nombre_col in ("id", "codigo", "código_rfid"):
                mapa_col.setdefault("codigo_rfid", idx)
            elif "sexo" in nombre_col or "clasificacion" in nombre_col:
                mapa_col.setdefault("sexo", idx)
            elif "fecha" in nombre_col or "nacimiento" in nombre_col:
                mapa_col.setdefault("fecha_nacimiento", idx)
            elif "raza" in nombre_col:
                mapa_col.setdefault("raza", idx)
            elif "estado" in nombre_col:
                mapa_col.setdefault("estado_actual", idx)
            elif "madre" in nombre_col:
                mapa_col.setdefault("madre_rfid", idx)
            elif "pajuela" in nombre_col or "lote" in nombre_col:
                mapa_col.setdefault("lote_pajuela", idx)

        # Si el archivo no tenía nombres estándar, asumir orden posicional:
        # [codigo_rfid, sexo, fecha_nacimiento, raza, estado_actual]
        if "codigo_rfid" not in mapa_col and len(encabezados_raw) >= 4:
            mapa_col = {
                "codigo_rfid": 0,
                "sexo": 1,
                "fecha_nacimiento": 2,
                "raza": 3,
                "estado_actual": 4 if len(encabezados_raw) > 4 else -1,
            }

        hoy = date.today()

        for num_fila, fila in enumerate(filas[1:], start=2):
            reporte["total_filas"] += 1

            def obtener_celda(clave, default=""):
                pos = mapa_col.get(clave, -1)
                if 0 <= pos < len(fila):
                    return (fila[pos] or "").strip()
                return default

            rfid_val = obtener_celda("codigo_rfid").upper()
            try:
                if not rfid_val:
                    raise ValueError("El código RFID es obligatorio y no puede estar vacío.")
                if len(rfid_val) < 3 or len(rfid_val) > 50:
                    raise ValueError(f"El código RFID '{rfid_val}' debe tener entre 3 y 50 caracteres.")

                sexo_val = _normalizar_sexo(obtener_celda("sexo"))
                fecha_nac = _parsear_fecha(obtener_celda("fecha_nacimiento"))
                if fecha_nac > hoy:
                    raise ValueError(f"La fecha de nacimiento ({fecha_nac}) no puede ser futura.")

                raza_nombre = obtener_celda("raza", "Angus") or "Angus"
                estado_val = obtener_celda("estado_actual", "Activo") or "Activo"
                madre_rfid = obtener_celda("madre_rfid").upper()
                lote_pajuela = obtener_celda("lote_pajuela").upper()

                raza_obj, _ = Raza.objects.get_or_create(
                    nombre_raza__iexact=raza_nombre,
                    defaults={"nombre_raza": raza_nombre.title(), "origen": "Registro Terreno"},
                )

                existente = Bovino.objects.filter(codigo_rfid=rfid_val).first()
                if existente:
                    if modo_duplicados == "actualizar":
                        existente.sexo = sexo_val
                        existente.fecha_nacimiento = fecha_nac
                        existente.raza = raza_obj
                        existente.estado_actual = estado_val
                        existente.save()
                        reporte["actualizados"] += 1
                        reporte["detalles"].append({
                            "fila": num_fila,
                            "rfid": rfid_val,
                            "estado": "Actualizado",
                            "tipo": "info",
                            "mensaje": f"{sexo_val} ({raza_obj.nombre_raza}) - Estado actualizado a '{estado_val}'.",
                        })
                    else:
                        reporte["omitidos"] += 1
                        reporte["detalles"].append({
                            "fila": num_fila,
                            "rfid": rfid_val,
                            "estado": "Omitido (Duplicado)",
                            "tipo": "warning",
                            "mensaje": "El código RFID ya se encuentra registrado en la base de datos.",
                        })
                    continue

                nuevo_bov = Bovino(
                    codigo_rfid=rfid_val,
                    sexo=sexo_val,
                    fecha_nacimiento=fecha_nac,
                    raza=raza_obj,
                    estado_actual=estado_val,
                )

                if lote_pajuela:
                    paj_obj = PajuelaSemen.objects.filter(lote_pajuela__iexact=lote_pajuela).first()
                    if paj_obj:
                        nuevo_bov.pajuela_semen = paj_obj

                nuevo_bov.save()

                if madre_rfid:
                    vaca_madre = Bovino.objects.filter(codigo_rfid=madre_rfid, sexo="Hembra").first()
                    if vaca_madre:
                        Parentesco.objects.get_or_create(
                            bovino=nuevo_bov,
                            ancestro=vaca_madre,
                            defaults={"generacion": 1, "coef_relacion": 0.5},
                        )

                reporte["creados"] += 1
                reporte["detalles"].append({
                    "fila": num_fila,
                    "rfid": rfid_val,
                    "estado": "Registrado",
                    "tipo": "success",
                    "mensaje": f"Ingresado correctamente: {sexo_val} | Raza: {raza_obj.nombre_raza} | Nac.: {fecha_nac.strftime('%d/%m/%Y')}",
                })

            except Exception as err_fila:
                reporte["errores"] += 1
                reporte["detalles"].append({
                    "fila": num_fila,
                    "rfid": rfid_val or "(Sin RFID)",
                    "estado": "Error de Validación",
                    "tipo": "danger",
                    "mensaje": str(err_fila),
                })

    except Exception as err_general:
        reporte["error_general"] = str(err_general)

    return reporte
