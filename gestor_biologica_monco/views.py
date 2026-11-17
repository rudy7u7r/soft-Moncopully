import json
import math
import random
import uuid
from datetime import timedelta
from django.utils import timezone
from django.core.exceptions import ValidationError
from django.db.models import Count, Q, Sum
from django.db.models.deletion import RestrictedError
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render, redirect
from .ingesta_exportacion import generar_xlsx_bytes, procesar_ingesta_rfid
from .rbac import (
    PERMISOS_POR_DEFECTO_ROL,
    asegurar_usuarios_iniciales,
    buscar_usuario_por_rut,
    cifrar_password,
    formatear_rut_visual,
    normalizar_rut,
    obtener_usuario_activo,
    verificar_password_usuario,
)
from .models import (
    Usuario,
    Bovino, 
    Inseminacion, 
    Parto, 
    AlertaConsanguinidad, 
    PajuelaSemen, 
    Raza, 
    Madre, 
    DiagnosticoGestacion, 
    vacas_disponibles,
    generar_lote,
    generar_toro_externo,
    Parentesco,
)

def _construir_metricas_reproductivas():
    bovinos_qs = Bovino.objects.filter(activo=True).select_related('raza').order_by('sexo', 'codigo_rfid')

    # Agregaciones en una sola pasada SQL para alto rendimiento con +1.500 bovinos
    ins_por_vaca = {
        r['vaca_id']: r['total']
        for r in Inseminacion.objects.filter(activo=True).values('vaca_id').annotate(total=Count('id_inseminacion'))
    }
    diags_por_vaca = {}
    for r in DiagnosticoGestacion.objects.values('inseminacion__vaca_id', 'resultado').annotate(total=Count('id_diagnostico')):
        vid = r['inseminacion__vaca_id']
        if vid not in diags_por_vaca:
            diags_por_vaca[vid] = {'preñada': 0, 'vacia': 0, 'mortinato': 0}
        diags_por_vaca[vid][r['resultado']] = r['total']

    partos_vivos_por_vaca = {
        r['diagnostico__inseminacion__vaca_id']: r['total']
        for r in Parto.objects.exclude(tipo_parto__icontains='mortinato')
        .values('diagnostico__inseminacion__vaca_id')
        .annotate(total=Count('id_parto'))
    }

    pajuelas_por_toro = {}
    for r in PajuelaSemen.objects.filter(toro__isnull=False, activo=True).values('toro_id').annotate(num_lotes=Count('id_pajuela'), stock_actual=Sum('stock')):
        pajuelas_por_toro[r['toro_id']] = {
            'num_lotes': r['num_lotes'],
            'stock_actual': r['stock_actual'] or 0,
        }

    ins_por_toro = {
        r['pajuela__toro_id']: r['total']
        for r in Inseminacion.objects.filter(pajuela__toro__isnull=False, activo=True)
        .values('pajuela__toro_id')
        .annotate(total=Count('id_inseminacion'))
    }

    diags_por_toro = {}
    for r in DiagnosticoGestacion.objects.filter(inseminacion__pajuela__toro__isnull=False).values('inseminacion__pajuela__toro_id', 'resultado').annotate(total=Count('id_diagnostico')):
        tid = r['inseminacion__pajuela__toro_id']
        if tid not in diags_por_toro:
            diags_por_toro[tid] = {'preñada': 0, 'vacia': 0, 'mortinato': 0}
        diags_por_toro[tid][r['resultado']] = r['total']

    bovinos_metricas = []
    for bov in bovinos_qs:
        item = {
            "id": bov.id_bovino,
            "codigo_rfid": bov.codigo_rfid,
            "sexo": bov.sexo,
            "raza": bov.raza.nombre_raza if bov.raza else "Sin raza",
            "fecha_nacimiento": bov.fecha_nacimiento.strftime("%d/%m/%Y") if bov.fecha_nacimiento else "-",
            "estado_actual": bov.estado_actual,
        }

        if bov.sexo == "Hembra":
            total_ins = ins_por_vaca.get(bov.id_bovino, 0)
            dv = diags_por_vaca.get(bov.id_bovino, {})
            preneces = dv.get('preñada', 0)
            vacias = dv.get('vacia', 0)
            mortinatos = dv.get('mortinato', 0)
            partos_vivos = partos_vivos_por_vaca.get(bov.id_bovino, 0)

            total_partos_o_eventos = partos_vivos + preneces + mortinatos
            tasa_mortalidad = round((mortinatos / total_partos_o_eventos) * 100, 1) if total_partos_o_eventos > 0 else 0.0
            tasa_exito = round((preneces / total_ins) * 100, 1) if total_ins > 0 else 0.0

            item.update({
                "total_inseminaciones": total_ins,
                "preneces_exitosas": preneces,
                "inseminaciones_vacias": vacias,
                "mortinatos": mortinatos,
                "partos_vivos": partos_vivos,
                "tasa_mortalidad": tasa_mortalidad,
                "tasa_exito": tasa_exito,
            })
        else:
            pt = pajuelas_por_toro.get(bov.id_bovino, {})
            num_lotes = pt.get('num_lotes', 0)
            stock_actual = pt.get('stock_actual', 0)
            total_ins_toro = ins_por_toro.get(bov.id_bovino, 0)
            pajuelas_extraidas_total = stock_actual + total_ins_toro

            dt = diags_por_toro.get(bov.id_bovino, {})
            exitos_toro = dt.get('preñada', 0)
            vacias_toro = dt.get('vacia', 0)
            mortinatos_toro = dt.get('mortinato', 0)
            tasa_exito_toro = round((exitos_toro / total_ins_toro) * 100, 1) if total_ins_toro > 0 else 0.0

            item.update({
                "lotes_extraidos": num_lotes,
                "stock_actual_pajuelas": stock_actual,
                "pajuelas_extraidas_total": pajuelas_extraidas_total,
                "inseminaciones_con_su_semen": total_ins_toro,
                "inseminaciones_exitosas": exitos_toro,
                "inseminaciones_vacias": vacias_toro,
                "mortinatos": mortinatos_toro,
                "tasa_exito": tasa_exito_toro,
            })

        bovinos_metricas.append(item)

    ins_por_pajuela = {
        r['pajuela_id']: r['total']
        for r in Inseminacion.objects.filter(activo=True).values('pajuela_id').annotate(total=Count('id_inseminacion'))
    }
    diags_por_pajuela = {}
    for r in DiagnosticoGestacion.objects.values('inseminacion__pajuela_id', 'resultado').annotate(total=Count('id_diagnostico')):
        pid = r['inseminacion__pajuela_id']
        if pid not in diags_por_pajuela:
            diags_por_pajuela[pid] = {'preñada': 0, 'vacia': 0, 'mortinato': 0}
        diags_por_pajuela[pid][r['resultado']] = r['total']

    pajuelas_qs = PajuelaSemen.objects.filter(activo=True).select_related('toro', 'toro__raza')
    pajuelas_metricas = []

    for paj in pajuelas_qs:
        usos = ins_por_pajuela.get(paj.id_pajuela, 0)
        dp = diags_por_pajuela.get(paj.id_pajuela, {})
        exitos = dp.get('preñada', 0)
        vacias = dp.get('vacia', 0)
        mortinatos = dp.get('mortinato', 0)
        pendientes = max(0, usos - (exitos + vacias + mortinatos))
        tasa_exito = round((exitos / usos) * 100, 1) if usos > 0 else 0.0

        if paj.toro:
            origen_str = f"Toro Local: {paj.toro.codigo_rfid} ({paj.toro.raza.nombre_raza})"
            tipo_origen = "Local"
        else:
            origen_str = f"Importado / Ext: {paj.codigo_toro_externo}"
            tipo_origen = "Importado"

        pajuelas_metricas.append({
            "id_pajuela": paj.id_pajuela,
            "lote_pajuela": paj.lote_pajuela,
            "origen": origen_str,
            "tipo_origen": tipo_origen,
            "stock": paj.stock,
            "usos": usos,
            "dosis_iniciales": paj.stock + usos,
            "exitos": exitos,
            "vacias": vacias,
            "mortinatos": mortinatos,
            "pendientes": pendientes,
            "tasa_exito": tasa_exito,
        })

    # Ordenar pajuelas por mayor cantidad de inseminaciones exitosas y mayor tasa de éxito
    pajuelas_metricas.sort(key=lambda x: (x["exitos"], x["tasa_exito"], x["usos"]), reverse=True)

    return bovinos_metricas, pajuelas_metricas


def inicio(request):
    today = timezone.localdate()
    
    total_bovinos = Bovino.objects.filter(activo=True).count()
    
    total_inseminaciones = Inseminacion.objects.filter(
        activo=True,
        fecha_servicio__year=today.year,
        fecha_servicio__month=today.month
    ).count()
    
    total_paridas = Parto.objects.filter(
        fecha_parto__year=today.year
    ).exclude(
        tipo_parto__icontains='mortinato'
    ).count()
    
    total_alertas = AlertaConsanguinidad.objects.count()
    
    # Series para el Gráfico de Mortalidad Neonatal (Día, Mes, Año)
    qs_mortinatos = DiagnosticoGestacion.objects.filter(resultado='mortinato')
    qs_partos_vivos = Parto.objects.exclude(tipo_parto__icontains='mortinato')

    # 1. Por Día (últimos 7 días)
    labels_dia = []
    mort_data_dia = []
    nac_data_dia = []
    for i in range(6, -1, -1):
        d = today - timedelta(days=i)
        labels_dia.append(d.strftime("%d/%m"))
        mort_data_dia.append(qs_mortinatos.filter(fecha_diagnostico=d).count())
        nac_data_dia.append(qs_partos_vivos.filter(fecha_parto=d).count())

    # 2. Por Mes (12 meses del año actual)
    nombres_meses = ['Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun', 'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic']
    mort_data_mes = []
    nac_data_mes = []
    for m in range(1, 13):
        mort_data_mes.append(qs_mortinatos.filter(fecha_diagnostico__year=today.year, fecha_diagnostico__month=m).count())
        nac_data_mes.append(qs_partos_vivos.filter(fecha_parto__year=today.year, fecha_parto__month=m).count())

    # 3. Por Año (últimos 5 años)
    labels_ano = []
    mort_data_ano = []
    nac_data_ano = []
    for y in range(today.year - 4, today.year + 1):
        labels_ano.append(str(y))
        mort_data_ano.append(qs_mortinatos.filter(fecha_diagnostico__year=y).count())
        nac_data_ano.append(qs_partos_vivos.filter(fecha_parto__year=y).count())

    ultimos_ingresos = Bovino.objects.filter(activo=True).order_by('-id_bovino')[:5]

    hembras = Bovino.objects.filter(sexo='Hembra', activo=True).count()
    machos = Bovino.objects.filter(sexo='Macho', activo=True).count()
    
    context = {
        'total_bovinos': total_bovinos,
        'total_inseminaciones': total_inseminaciones,
        'total_paridas': total_paridas,
        'total_alertas': total_alertas,
        'ultimos_ingresos': ultimos_ingresos,
        'chart_series_json': json.dumps({
            'dia': {'labels': labels_dia, 'mortalidad': mort_data_dia, 'nacimientos': nac_data_dia},
            'mes': {'labels': nombres_meses, 'mortalidad': mort_data_mes, 'nacimientos': nac_data_mes},
            'ano': {'labels': labels_ano, 'mortalidad': mort_data_ano, 'nacimientos': nac_data_ano},
        }),
        'chart_data_sexos': json.dumps([hembras, machos]),
    }
    
    return render(request, "gestor_biologica_monco/inicio.html", context)


def rendimiento_genetico(request):
    if request.method == "POST":
        accion = request.POST.get("accion")
        if accion == "deshabilitar_bovino":
            bid = request.POST.get("bovino_id")
            Bovino.objects.filter(pk=bid).update(activo=False)
        elif accion == "deshabilitar_pajuela":
            pid = request.POST.get("pajuela_id")
            PajuelaSemen.objects.filter(pk=pid).update(activo=False)
        return redirect("/rendimiento/")

    bovinos_metricas, pajuelas_metricas = _construir_metricas_reproductivas()
    vacas_metricas = [b for b in bovinos_metricas if b["sexo"] == "Hembra"]
    toros_metricas = [b for b in bovinos_metricas if b["sexo"] == "Macho"]

    return render(request, "gestor_biologica_monco/rendimiento.html", {
        "bovinos_metricas": bovinos_metricas,
        "vacas_metricas": vacas_metricas,
        "toros_metricas": toros_metricas,
        "pajuelas_metricas": pajuelas_metricas,
        "bovinos_metricas_json": json.dumps(bovinos_metricas),
    })


def historial(request):
    filtro = request.GET.get('filtro', 'todo')
    hoy = timezone.localdate()

    inseminaciones = Inseminacion.objects.filter(activo=True).select_related(
        "vaca", 
        "pajuela"
    ).order_by("-fecha_servicio")

    partos = Parto.objects.select_related(
        "cria", 
        "diagnostico__inseminacion__vaca"
    ).order_by("-fecha_parto")

    if filtro == 'dia':
        inseminaciones = inseminaciones.filter(fecha_servicio__date=hoy)
        partos = partos.filter(fecha_parto=hoy)
    elif filtro == 'semana':
        inicio_semana = hoy - timedelta(days=hoy.weekday())
        inseminaciones = inseminaciones.filter(fecha_servicio__date__gte=inicio_semana)
        partos = partos.filter(fecha_parto__gte=inicio_semana)
    elif filtro == 'mes':
        inseminaciones = inseminaciones.filter(fecha_servicio__year=hoy.year, fecha_servicio__month=hoy.month)
        partos = partos.filter(fecha_parto__year=hoy.year, fecha_parto__month=hoy.month)
    elif filtro == 'ano':
        inseminaciones = inseminaciones.filter(fecha_servicio__year=hoy.year)
        partos = partos.filter(fecha_parto__year=hoy.year)

    return render(
        request, 
        "gestor_biologica_monco/historial.html", 
        {
            "inseminaciones": inseminaciones,
            "partos": partos,
            "filtro_actual": filtro
        }
    )

def linaje(request):
    if request.method == "POST" and request.POST.get("accion") == "deshabilitar_bovino":
        bid = request.POST.get("bovino_id")
        Bovino.objects.filter(pk=bid).update(activo=False)
        return redirect("/linaje/")

    query = request.GET.get('q', '')
    bovino_id = request.GET.get('consultar') or request.GET.get('bovino') or ''
    
    bovinos = Bovino.objects.filter(activo=True).select_related("raza", "madre", "pajuela_semen__toro").order_by("-id_bovino")
    
    if query:
        bovinos = bovinos.filter(codigo_rfid__icontains=query)
        
    bovino_seleccionado = None
    antecesores = []
    sucesores = []
    
    if str(bovino_id).isdigit():
        bovino_seleccionado = Bovino.objects.filter(pk=int(bovino_id)).select_related(
            "raza", "madre", "pajuela_semen__toro", "pajuela_semen__toro__raza",
            "pajuela_semen__toro__madre", "pajuela_semen__toro__pajuela_semen__toro"
        ).first()
        if bovino_seleccionado:
            ids_ancestros_bovinos = set()

            # 1. Padre desde pajuela_semen
            if bovino_seleccionado.pajuela_semen:
                pajuela = bovino_seleccionado.pajuela_semen
                if pajuela.toro:
                    toro = pajuela.toro
                    ids_ancestros_bovinos.add(toro.id_bovino)
                    antecesores.append({
                        "relacion": "Padre (Toro Local)",
                        "identificador": toro.codigo_rfid,
                        "raza": toro.raza.nombre_raza if toro.raza else "Sin raza",
                        "detalle": f"Lote Pajuela: {pajuela.lote_pajuela}",
                        "estado": toro.estado_actual,
                        "id_bovino": toro.id_bovino,
                    })
                    if toro.pajuela_semen and toro.pajuela_semen.toro:
                        abuelo = toro.pajuela_semen.toro
                        ids_ancestros_bovinos.add(abuelo.id_bovino)
                        antecesores.append({
                            "relacion": "Abuelo Paterno",
                            "identificador": abuelo.codigo_rfid,
                            "raza": abuelo.raza.nombre_raza if abuelo.raza else "Sin raza",
                            "detalle": f"Lote Pajuela: {toro.pajuela_semen.lote_pajuela}",
                            "estado": abuelo.estado_actual,
                            "id_bovino": abuelo.id_bovino,
                        })
                    if toro.madre and (not bovino_seleccionado.madre or toro.madre_id != bovino_seleccionado.madre_id):
                        antecesores.append({
                            "relacion": "Abuela Paterna",
                            "identificador": f"Madre ID #{toro.madre.id_madregenero}",
                            "raza": "Hembra Reproductora",
                            "detalle": f"Fecha Nac.: {toro.madre.fecha_nacimiento.strftime('%d/%m/%Y')}",
                            "estado": toro.madre.estado_actual,
                            "id_bovino": None,
                        })
                elif pajuela.codigo_toro_externo:
                    antecesores.append({
                        "relacion": "Padre (Toro Externo)",
                        "identificador": pajuela.codigo_toro_externo,
                        "raza": "Semen Externo",
                        "detalle": f"Lote Pajuela: {pajuela.lote_pajuela}",
                        "estado": "Externo",
                        "id_bovino": None,
                    })

            # 2. Madre directa desde tabla Madre
            if bovino_seleccionado.madre:
                madre = bovino_seleccionado.madre
                antecesores.append({
                    "relacion": "Madre (Receptora)",
                    "identificador": f"Madre ID #{madre.id_madregenero}",
                    "raza": "Hembra Reproductora",
                    "detalle": f"Fecha Nac.: {madre.fecha_nacimiento.strftime('%d/%m/%Y')}",
                    "estado": madre.estado_actual,
                    "id_bovino": None,
                })

            # 3. Madre biológica registrada por Parto (si difiere del propio bovino)
            partos_como_cria = Parto.objects.filter(
                cria=bovino_seleccionado
            ).exclude(
                diagnostico__inseminacion__vaca=bovino_seleccionado
            ).select_related("diagnostico__inseminacion__vaca__raza")
            for p in partos_como_cria:
                vaca_madre = p.diagnostico.inseminacion.vaca
                if vaca_madre.id_bovino not in ids_ancestros_bovinos:
                    ids_ancestros_bovinos.add(vaca_madre.id_bovino)
                    antecesores.append({
                        "relacion": "Madre (Vaca en Sistema)",
                        "identificador": vaca_madre.codigo_rfid,
                        "raza": vaca_madre.raza.nombre_raza if vaca_madre.raza else "Sin raza",
                        "detalle": f"Parto: {p.fecha_parto.strftime('%d/%m/%Y')}",
                        "estado": vaca_madre.estado_actual,
                        "id_bovino": vaca_madre.id_bovino,
                    })

            # 4. Antecesores adicionales en la tabla Parentesco
            parentescos_ancestros = Parentesco.objects.filter(
                bovino=bovino_seleccionado
            ).select_related('ancestro', 'ancestro__raza')
            for par in parentescos_ancestros:
                if par.ancestro.id_bovino not in ids_ancestros_bovinos:
                    ids_ancestros_bovinos.add(par.ancestro.id_bovino)
                    if par.generacion == 1:
                        rel_nombre = "Padre (Toro Registrado)" if par.ancestro.sexo == "Macho" else "Madre (Vaca Registrada)"
                    else:
                        rel_nombre = f"Ancestro (Generación {par.generacion})"
                    antecesores.append({
                        "relacion": rel_nombre,
                        "identificador": par.ancestro.codigo_rfid,
                        "raza": par.ancestro.raza.nombre_raza if par.ancestro.raza else "Sin raza",
                        "detalle": f"Coef. Relación: {par.coef_relacion}",
                        "estado": par.ancestro.estado_actual,
                        "id_bovino": par.ancestro.id_bovino,
                    })

            # 5. Obtener sucesores (crías por pajuela del toro, por parto o por tabla Parentesco)
            sucesores = Bovino.objects.filter(
                Q(pajuela_semen__toro=bovino_seleccionado) |
                Q(parto_cria__diagnostico__inseminacion__vaca=bovino_seleccionado) |
                Q(parto_cria__diagnostico__inseminacion__pajuela__toro=bovino_seleccionado) |
                Q(parentescos_bovino__ancestro=bovino_seleccionado)
            ).exclude(
                pk=bovino_seleccionado.pk
            ).distinct().select_related('raza', 'pajuela_semen')

    return render(request, "gestor_biologica_monco/linaje.html", {
        "bovinos": bovinos,
        "bovino_seleccionado": bovino_seleccionado,
        "antecesores": antecesores,
        "sucesores": sucesores,
        "query": query
    })

def verificar(request):
    bovino_id = request.GET.get("bovino", "")
    bovino = None
    resultado_validacion = None
    mensaje_alerta = None
    
    if bovino_id.isdecimal():
        bovino = Bovino.objects.filter(pk=int(bovino_id)).first()
        
    if request.method == "POST" and bovino:
        tipo_reproductor = request.POST.get("tipo_reproductor")
        reproductor_id = request.POST.get("reproductor_id")
        
        try:
            if tipo_reproductor == "pajuela":
                pajuela = PajuelaSemen.objects.get(pk=reproductor_id)
                toro_semen = pajuela.toro
                
                if bovino.pajuela_semen and bovino.pajuela_semen.toro == toro_semen:
                    resultado_validacion = "peligro"
                    mensaje_alerta = "Alerta de Riesgo: El toro de esta pajuela es el padre directo de la vaca."
                elif toro_semen and bovino.madre and toro_semen.madre and bovino.madre == toro_semen.madre:
                    resultado_validacion = "peligro"
                    mensaje_alerta = "Alerta de Riesgo: La vaca y el toro comparten la misma madre (consanguinidad directa)."
                else:
                    resultado_validacion = "exito"
                    mensaje_alerta = "Validación Exitosa: El coeficiente de consanguinidad se encuentra en márgenes seguros."
                    
            elif tipo_reproductor == "toro":
                toro = Bovino.objects.get(pk=reproductor_id)
                
                if bovino.madre and toro.madre and bovino.madre == toro.madre:
                    resultado_validacion = "peligro"
                    mensaje_alerta = "Alerta de Riesgo: La vaca y el toro comparten la misma madre."
                else:
                    resultado_validacion = "exito"
                    mensaje_alerta = "Validación Exitosa: Cruza viable sin parentesco directo detectado."
                    
        except Exception as e:
            resultado_validacion = "peligro"
            mensaje_alerta = "Error al procesar la validación genética."

    toros_lista = Bovino.objects.filter(sexo='Macho').order_by('codigo_rfid')
    pajuelas_lista = PajuelaSemen.objects.filter(stock__gt=0).order_by('lote_pajuela')

    return render(
        request,
        "gestor_biologica_monco/verificar.html",
        {
            "bovino": bovino,
            "toros_lista": toros_lista,
            "pajuelas_lista": pajuelas_lista,
            "resultado_validacion": resultado_validacion,
            "mensaje_alerta": mensaje_alerta,
        },
    )

def login(request):
    asegurar_usuarios_iniciales()
    error_login = None
    es_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"

    if request.GET.get("logout") == "1":
        request.session.flush()

    if request.method == "POST":
        accion = (request.POST.get("accion") or "iniciar_sesion").strip()
        rut_raw = (request.POST.get("rut") or "").strip()
        rut_fmt = formatear_rut_visual(rut_raw)

        # 1. Paso 1: Verificar si el RUT está registrado en la base de datos
        if accion == "verificar_rut":
            if len(normalizar_rut(rut_raw)) < 3:
                return JsonResponse({"ok": False, "error": "Por favor ingrese un RUT válido."})

            usuario_db = buscar_usuario_por_rut(rut_raw)
            if usuario_db:
                return JsonResponse({
                    "ok": True,
                    "registrado": True,
                    "rut": usuario_db.rut,
                    "nombre": usuario_db.nombre_completo,
                    "email": usuario_db.email,
                })
            return JsonResponse({
                "ok": True,
                "registrado": False,
                "rut": rut_fmt,
            })

        # 2. Paso 2A: Iniciar sesión (RUT ya registrado)
        if accion == "iniciar_sesion":
            password = (request.POST.get("password") or "").strip()
            usuario_db = buscar_usuario_por_rut(rut_raw)

            if not usuario_db:
                msg = "El RUT ingresado aún no está registrado."
                if es_ajax:
                    return JsonResponse({"ok": False, "error": msg})
                error_login = msg
            elif not usuario_db.activo:
                msg = "Esta cuenta se encuentra deshabilitada por el Administrador."
                if es_ajax:
                    return JsonResponse({"ok": False, "error": msg})
                error_login = msg
            elif not verificar_password_usuario(usuario_db, password):
                msg = "Contraseña incorrecta. Puede usar la opción de recuperación vía Gmail."
                if es_ajax:
                    return JsonResponse({"ok": False, "error": msg})
                error_login = msg
            else:
                request.session["usuario_id"] = usuario_db.id_usuario
                request.session["usuario_rut"] = usuario_db.rut
                request.session["usuario_rol"] = usuario_db.rol
                request.session["mostrar_animacion_vaca"] = True
                destino = "/inicio/?bienvenida=1" if (usuario_db.aprobado_por_admin and usuario_db.rol != "pendiente") else "/esperando-permisos/"
                if es_ajax:
                    return JsonResponse({"ok": True, "redirect": destino, "mostrar_vaca": True})
                return redirect(destino)

        # 2B-pre: Verificar que el correo Gmail no esté ya registrado en otra cuenta
        if accion == "verificar_gmail":
            email = (request.POST.get("email") or "").strip().lower()
            if not email or "@" not in email:
                return JsonResponse({"ok": False, "error": "Ingrese una dirección de correo Gmail válida (ej. usuario@gmail.com)."})
            if Usuario.objects.filter(email__iexact=email).exists():
                return JsonResponse({
                    "ok": False,
                    "error": "Este correo Gmail ya se encuentra registrado en otra cuenta. Cada usuario debe tener un correo único.",
                })
            return JsonResponse({"ok": True, "email": email})

        # 3. Paso 2B: Registrar nuevo RUT con Gmail y Contraseña (queda esperando permisos del Admin)
        elif accion == "registrar_nuevo":
            email = (request.POST.get("email") or "").strip().lower()
            nombre = (request.POST.get("nombre_completo") or "").strip()
            password = (request.POST.get("password") or "").strip()

            if not rut_raw or not email or not password:
                msg = "Complete su correo Gmail y contraseña para registrarse."
                if es_ajax:
                    return JsonResponse({"ok": False, "error": msg})
                error_login = msg
            elif "@" not in email:
                msg = "Ingrese una dirección de correo Gmail válida (ej. usuario@gmail.com)."
                if es_ajax:
                    return JsonResponse({"ok": False, "error": msg})
                error_login = msg
            elif len(password) < 4:
                msg = "La contraseña debe tener al menos 4 caracteres."
                if es_ajax:
                    return JsonResponse({"ok": False, "error": msg})
                error_login = msg
            elif buscar_usuario_por_rut(rut_raw):
                msg = "Este RUT ya se encuentra registrado."
                if es_ajax:
                    return JsonResponse({"ok": False, "error": msg})
                error_login = msg
            elif Usuario.objects.filter(email__iexact=email).exists():
                msg = "Este correo Gmail ya se encuentra registrado en otra cuenta. Cada usuario debe tener un correo único."
                if es_ajax:
                    return JsonResponse({"ok": False, "error": msg})
                error_login = msg
            else:
                if not nombre:
                    nombre = email.split("@")[0].replace(".", " ").title()

                nuevo_u = Usuario.objects.create(
                    rut=rut_fmt,
                    nombre_completo=nombre,
                    email=email,
                    password=cifrar_password(password),
                    rol="pendiente",
                    aprobado_por_admin=False,
                    acceso_rendimiento=False,
                    acceso_inseminacion=False,
                    acceso_linaje=False,
                    acceso_pajuelas=False,
                    acceso_informes=False,
                    acceso_bovinos=False,
                    activo=True,
                )
                request.session["usuario_id"] = nuevo_u.id_usuario
                request.session["usuario_rut"] = nuevo_u.rut
                request.session["usuario_rol"] = nuevo_u.rol
                if es_ajax:
                    return JsonResponse({"ok": True, "redirect": "/esperando-permisos/"})
                return redirect("/esperando-permisos/")

        # 4. Simulación de envío de código de recuperación a Gmail
        elif accion == "solicitar_codigo_gmail":
            usuario_db = buscar_usuario_por_rut(rut_raw)
            if not usuario_db:
                return JsonResponse({"ok": False, "error": "No se encontró una cuenta asociada a este RUT."})

            codigo = str(random.randint(100000, 999999))
            request.session["recup_rut"] = usuario_db.rut
            request.session["recup_codigo"] = codigo
            return JsonResponse({
                "ok": True,
                "email": usuario_db.email,
                "codigo_simulado": codigo,
                "mensaje": f"Se ha enviado un código de verificación a {usuario_db.email}.",
            })

        # 5. Validar código de Gmail y cambiar contraseña
        elif accion == "cambiar_password_codigo":
            codigo_ingresado = (request.POST.get("codigo") or "").strip()
            nueva_password = (request.POST.get("nueva_password") or "").strip()
            usuario_db = buscar_usuario_por_rut(rut_raw)

            codigo_guardado = request.session.get("recup_codigo")
            rut_guardado = request.session.get("recup_rut")

            if not usuario_db or normalizar_rut(usuario_db.rut) != normalizar_rut(rut_guardado):
                return JsonResponse({"ok": False, "error": "Sesión de recuperación expirada. Solicite un nuevo código."})
            if not codigo_ingresado or codigo_ingresado != codigo_guardado:
                return JsonResponse({"ok": False, "error": "El código ingresado no coincide con el enviado a su Gmail."})
            if len(nueva_password) < 4:
                return JsonResponse({"ok": False, "error": "La nueva contraseña debe tener al menos 4 caracteres."})

            usuario_db.password = cifrar_password(nueva_password)
            usuario_db.save(update_fields=["password"])
            request.session.pop("recup_codigo", None)
            request.session.pop("recup_rut", None)

            return JsonResponse({
                "ok": True,
                "mensaje": "Contraseña actualizada exitosamente. Ahora puede iniciar sesión con su nueva clave.",
            })

    return render(request, "gestor_biologica_monco/login.html", {
        "error": error_login,
    })


def esperando_permisos(request):
    asegurar_usuarios_iniciales()
    uid = request.session.get("usuario_id")
    usuario = Usuario.objects.filter(pk=uid).first() if uid else None

    if not usuario:
        return redirect("/login/")

    # Si el Administrador ya le otorgó rol y permisos, redirigir directamente al software
    if usuario.aprobado_por_admin and usuario.rol != "pendiente":
        request.session["usuario_rol"] = usuario.rol
        if request.GET.get("check") == "1":
            return JsonResponse({"aprobado": True, "redirect": "/inicio/"})
        return redirect("/inicio/")

    if request.GET.get("check") == "1":
        return JsonResponse({"aprobado": False})

    return render(request, "gestor_biologica_monco/esperando_permisos.html", {
        "usuario_espera": usuario,
    })


def gestion_usuarios(request):
    asegurar_usuarios_iniciales()
    mensaje_exito = None
    mensaje_error = None
    usuario_admin = obtener_usuario_activo(request)

    if request.GET.get("lock") == "1":
        request.session.pop("usuarios_desbloqueado", None)
        return redirect("/usuarios/")

    if request.method == "POST":
        accion = request.POST.get("accion")

        if accion == "desbloquear_panel":
            password_ingresada = (request.POST.get("password_admin") or "").strip()
            if usuario_admin and verificar_password_usuario(usuario_admin, password_ingresada):
                request.session["usuarios_desbloqueado"] = True
                mensaje_exito = "Identidad verificada. Panel de Roles y Permisos desbloqueado."
            else:
                mensaje_error = "Contraseña de Administrador incorrecta. No se pudo desbloquear el panel."
        elif not request.session.get("usuarios_desbloqueado"):
            mensaje_error = "Por seguridad, debe ingresar su contraseña de Administrador para desbloquear Roles y Permisos."
        else:
            try:
                if accion == "asignar_permisos":
                    uid = request.POST.get("usuario_id")
                    u_obj = Usuario.objects.get(pk=uid)
                    rol = (request.POST.get("rol") or "operario").strip()
                    if rol not in ("admin", "veterinario", "operario"):
                        rol = "operario"

                    es_admin_edit = rol == "admin"
                    u_obj.rol = rol
                    u_obj.aprobado_por_admin = True
                    u_obj.acceso_rendimiento = True if es_admin_edit else (request.POST.get("acceso_rendimiento") == "on")
                    u_obj.acceso_inseminacion = True if es_admin_edit else (request.POST.get("acceso_inseminacion") == "on")
                    u_obj.acceso_linaje = True if es_admin_edit else (request.POST.get("acceso_linaje") == "on")
                    u_obj.acceso_pajuelas = True if es_admin_edit else (request.POST.get("acceso_pajuelas") == "on")
                    u_obj.acceso_informes = True if es_admin_edit else (request.POST.get("acceso_informes") == "on")
                    u_obj.acceso_bovinos = True if es_admin_edit else (request.POST.get("acceso_bovinos") == "on")
                    u_obj.activo = True
                    u_obj.save()
                    mensaje_exito = f"Rol ({u_obj.get_rol_display()}) y permisos otorgados a {u_obj.rut} ({u_obj.email})."

                elif accion == "poner_en_espera":
                    uid = request.POST.get("usuario_id")
                    u_obj = Usuario.objects.get(pk=uid)
                    if normalizar_rut(u_obj.rut) in ("1111111-1", "22127234-K"):
                        raise ValidationError("La cuenta principal de Administrador no puede ser puesta en espera.")
                    if u_obj.rol == "admin" and Usuario.objects.filter(rol="admin", aprobado_por_admin=True).count() <= 1:
                        raise ValidationError("No se puede revocar el acceso al único Administrador activo.")
                    u_obj.rol = "pendiente"
                    u_obj.aprobado_por_admin = False
                    u_obj.acceso_rendimiento = False
                    u_obj.acceso_inseminacion = False
                    u_obj.acceso_linaje = False
                    u_obj.acceso_pajuelas = False
                    u_obj.acceso_informes = False
                    u_obj.acceso_bovinos = False
                    u_obj.save()
                    mensaje_exito = f"Los permisos del usuario {u_obj.rut} fueron revocados (En espera)."

                elif accion in ("deshabilitar_usuario", "eliminar_usuario"):
                    uid = request.POST.get("usuario_id")
                    u_obj = Usuario.objects.get(pk=uid)
                    if normalizar_rut(u_obj.rut) in ("1111111-1", "22127234-K"):
                        raise ValidationError("La cuenta principal de Administrador no puede ser deshabilitada del sistema.")
                    if u_obj.rol == "admin" and Usuario.objects.filter(rol="admin", aprobado_por_admin=True, activo=True).count() <= 1:
                        raise ValidationError("No se puede deshabilitar el único Administrador activo del sistema.")
                    u_obj.activo = False
                    u_obj.save(update_fields=["activo"])
                    mensaje_exito = f"El usuario con RUT {u_obj.rut} fue deshabilitado (su registro permanece guardado en la base de datos)."

            except ValidationError as e:
                mensaje_error = e.message
            except Exception:
                mensaje_error = "Ocurrió un error al actualizar los permisos del usuario."

    panel_bloqueado = not bool(request.session.get("usuarios_desbloqueado"))
    busqueda_rut = (request.GET.get("rut") or request.GET.get("q") or "").strip()
    usuarios_pendientes = list(Usuario.objects.filter(aprobado_por_admin=False, activo=True).order_by("-id_usuario"))
    usuarios_aprobados = list(Usuario.objects.filter(aprobado_por_admin=True, activo=True).order_by("id_usuario"))

    if busqueda_rut:
        q_limpio = "".join(ch for ch in busqueda_rut.upper() if ch.isalnum())
        usuarios_pendientes = [
            u for u in usuarios_pendientes
            if busqueda_rut.lower() in u.rut.lower()
            or (q_limpio and q_limpio in "".join(ch for ch in u.rut.upper() if ch.isalnum()))
        ]
        usuarios_aprobados = [
            u for u in usuarios_aprobados
            if busqueda_rut.lower() in u.rut.lower()
            or (q_limpio and q_limpio in "".join(ch for ch in u.rut.upper() if ch.isalnum()))
        ]

    return render(request, "gestor_biologica_monco/usuarios.html", {
        "panel_bloqueado": panel_bloqueado,
        "usuarios_pendientes": usuarios_pendientes,
        "usuarios_aprobados": usuarios_aprobados,
        "busqueda_rut": busqueda_rut,
        "mensaje_exito": mensaje_exito,
        "mensaje_error": mensaje_error,
    })

def inseminacion(request):
    if request.method == "POST" and request.POST.get("accion") == "deshabilitar_inseminacion":
        ins_id = request.POST.get("inseminacion_id")
        Inseminacion.objects.filter(pk=ins_id).update(activo=False)
        return redirect("/inseminacion/")

    lista_inseminaciones = Inseminacion.objects.filter(activo=True).select_related('vaca', 'pajuela').order_by('-fecha_servicio')
    return render(request, "gestor_biologica_monco/inseminacion.html", {"inseminaciones": lista_inseminaciones})

def pajuelas(request):
    mensaje_exito = None
    mensaje_error = None
    es_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"

    if request.method == "POST":
        accion = request.POST.get("accion")
        pajuela_id = request.POST.get("pajuela_id")
        pajuela_obj = None

        try:
            pajuela_obj = PajuelaSemen.objects.get(pk=pajuela_id)

            if accion == "editar_lote":
                nuevo_lote = (request.POST.get("lote_pajuela") or "").strip()
                nueva_fecha = request.POST.get("fecha_extraccion")

                if not nuevo_lote:
                    mensaje_error = "El código de lote no puede quedar vacío."
                elif PajuelaSemen.objects.filter(lote_pajuela=nuevo_lote).exclude(pk=pajuela_obj.pk).exists():
                    mensaje_error = f"Ya existe otro lote registrado con el código {nuevo_lote}."
                else:
                    pajuela_obj.lote_pajuela = nuevo_lote
                    if nueva_fecha:
                        pajuela_obj.fecha_extraccion = nueva_fecha
                    pajuela_obj.save(update_fields=["lote_pajuela", "fecha_extraccion"])
                    mensaje_exito = f"Lote {pajuela_obj.lote_pajuela} actualizado correctamente."

            elif accion in ("deshabilitar", "eliminar"):
                nombre_lote = pajuela_obj.lote_pajuela
                pajuela_obj.activo = False
                pajuela_obj.save(update_fields=["activo"])
                mensaje_exito = f"El lote {nombre_lote} fue deshabilitado (se conserva almacenado en la base de datos)."

        except PajuelaSemen.DoesNotExist:
            mensaje_error = "El lote seleccionado no fue encontrado."
        except Exception:
            mensaje_error = "Error al procesar la acción sobre el lote de pajuelas."

        if es_ajax:
            todas_qs = PajuelaSemen.objects.filter(activo=True)
            return JsonResponse({
                "ok": mensaje_error is None,
                "mensaje": mensaje_exito or mensaje_error,
                "pajuela_id": pajuela_id,
                "stock": pajuela_obj.stock if pajuela_obj else 0,
                "lote_pajuela": pajuela_obj.lote_pajuela if pajuela_obj else "",
                "es_critico": (pajuela_obj.stock <= 10) if pajuela_obj else True,
                "total_lotes": todas_qs.count(),
                "total_dosis": todas_qs.aggregate(total=Sum('stock'))['total'] or 0,
                "total_locales": todas_qs.filter(toro__isnull=False).count(),
                "total_importados": todas_qs.filter(toro__isnull=True).count(),
                "total_criticos": todas_qs.filter(stock__lte=10).count(),
            })

    filtro = request.GET.get("filtro", "todos")
    busqueda = (request.GET.get("q") or "").strip()

    todas_pajuelas = PajuelaSemen.objects.filter(activo=True).select_related('toro', 'toro__raza').order_by('-fecha_extraccion', '-id_pajuela')

    # Estadísticas globales del inventario
    total_lotes = todas_pajuelas.count()
    total_dosis = todas_pajuelas.aggregate(total=Sum('stock'))['total'] or 0
    total_locales = todas_pajuelas.filter(toro__isnull=False).count()
    total_importados = todas_pajuelas.filter(toro__isnull=True).count()
    total_criticos = todas_pajuelas.filter(stock__lte=10).count()

    lista_pajuelas = todas_pajuelas
    if filtro == "locales":
        lista_pajuelas = lista_pajuelas.filter(toro__isnull=False)
    elif filtro == "importados":
        lista_pajuelas = lista_pajuelas.filter(toro__isnull=True)
    elif filtro == "criticos":
        lista_pajuelas = lista_pajuelas.filter(stock__lte=10)

    if busqueda:
        lista_pajuelas = lista_pajuelas.filter(
            Q(lote_pajuela__icontains=busqueda)
            | Q(codigo_toro_externo__icontains=busqueda)
            | Q(toro__codigo_rfid__icontains=busqueda)
            | Q(toro__raza__nombre_raza__icontains=busqueda)
        )

    return render(request, "gestor_biologica_monco/pajuelas.html", {
        "pajuelas": lista_pajuelas,
        "filtro_actual": filtro,
        "busqueda": busqueda,
        "total_lotes": total_lotes,
        "total_dosis": total_dosis,
        "total_locales": total_locales,
        "total_importados": total_importados,
        "total_criticos": total_criticos,
        "mensaje_exito": mensaje_exito,
        "mensaje_error": mensaje_error,
    })

def nueva_pajuela(request):
    error_msg = None
    tipo_seleccionado = request.GET.get("tipo", "toro_local")

    if request.method == "POST":
        tipo_origen = request.POST.get("tipo_origen", "toro_local")
        tipo_seleccionado = tipo_origen
        lote_input = (request.POST.get("lote_pajuela") or "").strip().upper()
        fecha_extraccion = request.POST.get("fecha_extraccion")
        stock_str = request.POST.get("stock", "0")

        try:
            stock = int(stock_str)
            if stock <= 0:
                raise ValidationError("La cantidad de pajuelas (stock) debe ser mayor a 0.")
            if not fecha_extraccion:
                raise ValidationError("Debe indicar la fecha de extracción o recepción del lote.")

            lote_final = lote_input if lote_input else generar_lote()
            if PajuelaSemen.objects.filter(lote_pajuela=lote_final).exists():
                raise ValidationError(f"Ya existe un lote registrado con el código '{lote_final}'. Ingrese uno distinto o déjelo en blanco para autogenerarlo.")

            if tipo_origen == "toro_local":
                toro_id = request.POST.get("toro_id")
                if not toro_id:
                    raise ValidationError("Debe seleccionar un toro registrado de la parcela.")
                toro_obj = Bovino.objects.get(pk=toro_id, sexo='Macho')

                PajuelaSemen.objects.create(
                    toro=toro_obj,
                    codigo_toro_externo=None,
                    lote_pajuela=lote_final,
                    fecha_extraccion=fecha_extraccion,
                    stock=stock,
                )
            else:
                pais_origen = (request.POST.get("pais_origen") or "USA").strip().upper()
                codigo_ext_input = (request.POST.get("codigo_toro_externo") or "").strip().upper()

                if codigo_ext_input:
                    if not codigo_ext_input.startswith(pais_origen):
                        codigo_final = f"{pais_origen}-{codigo_ext_input}"
                    else:
                        codigo_final = codigo_ext_input
                else:
                    codigo_final = f"{pais_origen}-{str(uuid.uuid4().hex)[:6].upper()}"

                if not lote_input:
                    lote_final = f"LOTE-{pais_origen}-{str(uuid.uuid4().hex)[:6].upper()}"

                PajuelaSemen.objects.create(
                    toro=None,
                    codigo_toro_externo=codigo_final,
                    lote_pajuela=lote_final,
                    fecha_extraccion=fecha_extraccion,
                    stock=stock,
                )

            return redirect('/pajuelas/')

        except ValidationError as e:
            error_msg = e.message
        except Exception:
            error_msg = "Error al guardar el lote de pajuelas. Verifique los datos ingresados."

    toros_locales = Bovino.objects.filter(sexo='Macho').select_related('raza').order_by('codigo_rfid')
    fecha_hoy = timezone.localdate().isoformat()

    return render(request, "gestor_biologica_monco/nueva_pajuela.html", {
        "toros_locales": toros_locales,
        "tipo_seleccionado": tipo_seleccionado,
        "fecha_hoy": fecha_hoy,
        "error": error_msg,
    })

def informes(request):
    reporte_carga = None
    if request.method == "POST" and request.FILES.get("archivo_rfid"):
        archivo = request.FILES["archivo_rfid"]
        modo_duplicados = request.POST.get("modo_duplicados", "omitir")
        reporte_carga = procesar_ingesta_rfid(archivo, modo_duplicados=modo_duplicados)

    total_bovinos = Bovino.objects.filter(activo=True).count()
    total_inseminaciones = Inseminacion.objects.filter(activo=True).count()
    total_pajuelas = PajuelaSemen.objects.filter(activo=True).count()
    total_alertas = AlertaConsanguinidad.objects.count()

    return render(request, "gestor_biologica_monco/informes.html", {
        "reporte_carga": reporte_carga,
        "total_bovinos": total_bovinos,
        "total_inseminaciones": total_inseminaciones,
        "total_pajuelas": total_pajuelas,
        "total_alertas": total_alertas,
    })


def ingreso_masivo_registros(request):
    reporte_carga = None
    if request.method == "POST" and request.FILES.get("archivo_rfid"):
        archivo = request.FILES["archivo_rfid"]
        modo_duplicados = request.POST.get("modo_duplicados", "omitir")
        reporte_carga = procesar_ingesta_rfid(archivo, modo_duplicados=modo_duplicados)

    total_bovinos = Bovino.objects.filter(activo=True).count()
    total_inseminaciones = Inseminacion.objects.filter(activo=True).count()
    total_pajuelas = PajuelaSemen.objects.filter(activo=True).count()

    return render(request, "gestor_biologica_monco/ingreso_masivo_informes.html", {
        "reporte_carga": reporte_carga,
        "total_bovinos": total_bovinos,
        "total_inseminaciones": total_inseminaciones,
        "total_pajuelas": total_pajuelas,
    })


def _respuesta_excel(nombre_archivo, nombre_hoja, encabezados, filas, formato="xlsx"):
    if formato == "csv":
        import csv
        import io
        buf = io.StringIO()
        buf.write("\ufeff")  # BOM UTF-8 para apertura directa en Excel
        writer = csv.writer(buf, delimiter=";")
        writer.writerow(encabezados)
        for fila in filas:
            writer.writerow(fila)
        resp = HttpResponse(buf.getvalue(), content_type="text/csv; charset=utf-8")
        resp["Content-Disposition"] = f'attachment; filename="{nombre_archivo}.csv"'
        return resp

    xlsx_bytes = generar_xlsx_bytes(nombre_hoja, encabezados, filas)
    resp = HttpResponse(
        xlsx_bytes,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    resp["Content-Disposition"] = f'attachment; filename="{nombre_archivo}.xlsx"'
    return resp


def exportar_inseminaciones(request):
    mes_filtro = (request.GET.get("mes_filtro") or "").strip()
    formato = request.GET.get("formato", "xlsx")
    qs = Inseminacion.objects.select_related("vaca", "vaca__raza", "pajuela", "pajuela__toro").order_by("-fecha_servicio")

    if mes_filtro and "-" in mes_filtro:
        partes = mes_filtro.split("-")
        if len(partes) == 2 and partes[0].isdigit() and partes[1].isdigit():
            qs = qs.filter(
                fecha_servicio__year=int(partes[0]),
                fecha_servicio__month=int(partes[1]),
            )

    encabezados = [
        "ID Inseminación",
        "Código RFID Vaca",
        "Raza Vaca",
        "Lote Pajuela",
        "Toro / Origen Semen",
        "Fecha de Servicio",
        "Resultado Diagnóstico",
        "Semanas Gestación",
        "Fecha Diagnóstico",
    ]
    filas = []
    for ins in qs:
        diag = DiagnosticoGestacion.objects.filter(inseminacion=ins).first()
        if ins.pajuela.toro:
            origen_semen = f"Local: {ins.pajuela.toro.codigo_rfid}"
        else:
            origen_semen = f"Importado: {ins.pajuela.codigo_toro_externo}"

        if diag:
            if diag.resultado == "preñada":
                res_txt = "Preñada"
            elif diag.resultado == "mortinato":
                res_txt = "Ternero Murió en el Parto"
            else:
                res_txt = "Vacía"
            sem_val = diag.semanas
            fec_diag = diag.fecha_diagnostico.strftime("%d/%m/%Y")
        else:
            res_txt = "Pendiente"
            sem_val = 0
            fec_diag = "-"

        filas.append([
            ins.id_inseminacion,
            ins.vaca.codigo_rfid,
            ins.vaca.raza.nombre_raza if ins.vaca.raza else "-",
            ins.pajuela.lote_pajuela,
            origen_semen,
            ins.fecha_servicio.strftime("%d/%m/%Y"),
            res_txt,
            sem_val,
            fec_diag,
        ])

    return _respuesta_excel("Reporte_Inseminaciones_Moncopulli", "Inseminaciones", encabezados, filas, formato)


def exportar_alertas(request):
    estado = (request.GET.get("estado") or "todas").strip().lower()
    formato = request.GET.get("formato", "xlsx")
    qs = AlertaConsanguinidad.objects.select_related("vaca", "toro").order_by("-fecha")
    if estado == "bloqueada":
        qs = qs.filter(estado__icontains="bloq")

    encabezados = [
        "ID Alerta",
        "RFID Vaca",
        "RFID Toro",
        "Coeficiente Proyectado (F)",
        "Fecha y Hora",
        "Estado",
    ]
    filas = []
    for al in qs:
        filas.append([
            al.id_alerta,
            al.vaca.codigo_rfid,
            al.toro.codigo_rfid,
            float(al.f_proyectado),
            al.fecha.strftime("%d/%m/%Y %H:%M"),
            al.estado,
        ])

    return _respuesta_excel("Reporte_Alertas_Consanguinidad", "Alertas", encabezados, filas, formato)


def exportar_inventario(request):
    filtro_stock = (request.GET.get("stock") or "todos").strip().lower()
    formato = request.GET.get("formato", "xlsx")
    qs = PajuelaSemen.objects.select_related("toro", "toro__raza").order_by("lote_pajuela")
    if filtro_stock == "critico":
        qs = qs.filter(stock__lte=10)

    encabezados = [
        "Código Lote",
        "Tipo de Origen",
        "Reproductor / Identificador",
        "Raza Toro",
        "Fecha Extracción / Recepción",
        "Stock Disponible",
        "Inseminaciones Realizadas",
        "Inseminaciones Exitosas",
        "Estado Stock",
    ]
    filas = []
    for p in qs:
        usos = Inseminacion.objects.filter(pajuela=p).count()
        exitos = DiagnosticoGestacion.objects.filter(inseminacion__pajuela=p, resultado="preñada").count()
        filas.append([
            p.lote_pajuela,
            "Toro Local" if p.toro else "Importado / Externo",
            p.toro.codigo_rfid if p.toro else (p.codigo_toro_externo or "-"),
            p.toro.raza.nombre_raza if (p.toro and p.toro.raza) else "Catálogo Externo",
            p.fecha_extraccion.strftime("%d/%m/%Y"),
            p.stock,
            usos,
            exitos,
            "Stock Crítico" if p.stock <= 10 else "Suficiente",
        ])

    return _respuesta_excel("Inventario_Pajuelas_Moncopulli", "Inventario_Pajuelas", encabezados, filas, formato)


def exportar_ganado_terreno(request):
    formato = request.GET.get("formato", "xlsx")
    tipo_filtro = (request.GET.get("sexo") or "todos").strip()
    bovinos_metricas, _ = _construir_metricas_reproductivas()
    if tipo_filtro in ("Hembra", "Macho"):
        bovinos_metricas = [b for b in bovinos_metricas if b["sexo"] == tipo_filtro]

    encabezados = [
        "Código RFID",
        "Clasificación (Sexo)",
        "Raza",
        "Fecha Nacimiento",
        "Estado Actual",
        "Servicios / Inseminaciones",
        "Preñeces Exitosas",
        "Tasa Éxito (%)",
        "Mortalidad Parto (%) / Lotes Toro",
        "Observación Terreno (Completar Offline)",
    ]
    filas = []
    for b in bovinos_metricas:
        if b["sexo"] == "Hembra":
            serv = b["total_inseminaciones"]
            exitos = b["preneces_exitosas"]
            extra = f"Mortalidad parto: {b['tasa_mortalidad']}% ({b['mortinatos']} mortinatos)"
        else:
            serv = b["inseminaciones_con_su_semen"]
            exitos = b["inseminaciones_exitosas"]
            extra = f"Lotes: {b['lotes_extraidos']} | Stock: {b['stock_actual_pajuelas']} / Extraídas: {b['pajuelas_extraidas_total']}"

        filas.append([
            b["codigo_rfid"],
            b["sexo"],
            b["raza"],
            b["fecha_nacimiento"],
            b["estado_actual"],
            serv,
            exitos,
            b["tasa_exito"],
            extra,
            "",
        ])

    return _respuesta_excel("Planilla_Terreno_Ganado_Moncopulli", "Ganado_Terreno", encabezados, filas, formato)


def descargar_plantilla_rfid(request):
    formato = request.GET.get("formato", "xlsx")
    encabezados = [
        "codigo_rfid",
        "sexo",
        "fecha_nacimiento",
        "raza",
        "estado_actual",
        "madre_rfid",
        "lote_pajuela",
    ]
    filas_ejemplo = [
        ["MONCO-TERR-101", "Hembra", "2024-03-15", "Angus", "Reproductora", "", ""],
        ["MONCO-TERR-102", "Macho", "2024-04-20", "Hereford", "Activo", "", ""],
        ["MONCO-TERR-103", "Hembra", "2024-06-10", "Angus", "Vaquilla", "MONCO-TERR-101", ""],
    ]
    return _respuesta_excel("Plantilla_Carga_RFID_Moncopulli", "Plantilla_RFID", encabezados, filas_ejemplo, formato)

def nueva_inseminacion(request):
    error_msg = None
    
    if request.method == 'POST':
        vaca_id = request.POST.get('vaca_id')
        pajuela_id = request.POST.get('pajuela_id')
        fecha_servicio = request.POST.get('fecha_servicio')
        
        try:
            vaca = Bovino.objects.get(pk=vaca_id)
            pajuela = PajuelaSemen.objects.get(pk=pajuela_id)
            
            nueva_ins = Inseminacion(vaca=vaca, pajuela=pajuela, fecha_servicio=fecha_servicio)
            nueva_ins.clean() 
            nueva_ins.save()

            if pajuela.stock > 0:
                pajuela.stock -= 1
                pajuela.save(update_fields=['stock'])
            
            return redirect('/inseminacion/')
            
        except ValidationError as e:
            error_msg = e.message
        except Exception as e:
            error_msg = "Error al procesar el registro. Verifique los datos."

    # Se usa directamente la función importada desde models.py
    vacas = vacas_disponibles().order_by('codigo_rfid')
    pajuelas = PajuelaSemen.objects.filter(stock__gt=0).order_by('lote_pajuela')
    
    return render(request, "gestor_biologica_monco/nueva_inseminacion.html", {
        "vacas": vacas,
        "pajuelas": pajuelas,
        "error": error_msg
    })


def inseminacion_masiva(request):
    """
    Inyección / Inseminación Masiva por Escaneo RFID.
    Permite que 1 pajuela rinda para N vacas (por defecto 3 vacas por 1 pajuela),
    escaneando múltiples códigos RFID de vacas para inyectarlas de una sola vez
    y descontando proporcionalmente las pajuelas utilizadas.
    """
    error_msg = None
    reporte_masivo = None

    if request.method == "POST":
        pajuela_id = request.POST.get("pajuela_id")
        fecha_servicio = request.POST.get("fecha_servicio") or timezone.localdate().isoformat()
        vacas_por_pajuela_str = request.POST.get("vacas_por_pajuela", "3")
        rfids_raw = request.POST.get("rfids_escaneados", "")

        try:
            vacas_por_pajuela = max(1, int(vacas_por_pajuela_str))
        except ValueError:
            vacas_por_pajuela = 3

        # Extraer lista única de códigos RFID escaneados o separados por salto de línea / coma
        codigos_rfid = []
        vistos = set()
        for token in rfids_raw.replace(",", "\n").replace(";", "\n").splitlines():
            limpio = token.strip().upper()
            if limpio and limpio not in vistos:
                vistos.add(limpio)
                codigos_rfid.append(limpio)

        if not pajuela_id:
            error_msg = "Debe seleccionar el lote de pajuela que utilizará para la inyección masiva."
        elif not codigos_rfid:
            error_msg = "Debe escanear o agregar al menos una vaca por su código RFID."
        else:
            try:
                pajuela = PajuelaSemen.objects.select_related("toro").get(pk=pajuela_id)
                pajuelas_requeridas = math.ceil(len(codigos_rfid) / vacas_por_pajuela)

                if pajuela.stock < pajuelas_requeridas:
                    error_msg = (
                        f"Stock insuficiente en el lote {pajuela.lote_pajuela}: "
                        f"para inyectar {len(codigos_rfid)} vacas (rendimiento: 1 pajuela cada {vacas_por_pajuela} vacas) "
                        f"se necesitan {pajuelas_requeridas} pajuelas, pero solo hay {pajuela.stock} disponibles."
                    )
                else:
                    mapa_vacas = {
                        b.codigo_rfid.upper(): b
                        for b in Bovino.objects.filter(sexo="Hembra").select_related("raza")
                    }
                    inyectadas_ok = []
                    rechazadas = []

                    for rfid_code in codigos_rfid:
                        vaca_obj = mapa_vacas.get(rfid_code)
                        if not vaca_obj:
                            rechazadas.append({
                                "rfid": rfid_code,
                                "motivo": "Código RFID no encontrado como Vaca (Hembra) en la base de datos.",
                            })
                            continue

                        try:
                            nueva_ins = Inseminacion(
                                vaca=vaca_obj,
                                pajuela=pajuela,
                                fecha_servicio=fecha_servicio,
                            )
                            nueva_ins.clean()
                            nueva_ins.save()
                            inyectadas_ok.append({
                                "rfid": vaca_obj.codigo_rfid,
                                "raza": vaca_obj.raza.nombre_raza if vaca_obj.raza else "-",
                                "id_inseminacion": nueva_ins.id_inseminacion,
                            })
                        except ValidationError as ve:
                            rechazadas.append({
                                "rfid": vaca_obj.codigo_rfid,
                                "motivo": ve.message if hasattr(ve, "message") else "; ".join(ve.messages),
                            })
                        except Exception:
                            rechazadas.append({
                                "rfid": vaca_obj.codigo_rfid,
                                "motivo": "Error al validar o registrar la inseminación de esta vaca.",
                            })

                    pajuelas_descontadas = (
                        math.ceil(len(inyectadas_ok) / vacas_por_pajuela) if inyectadas_ok else 0
                    )
                    if pajuelas_descontadas > 0:
                        pajuela.stock = max(0, pajuela.stock - pajuelas_descontadas)
                        pajuela.save(update_fields=["stock"])

                    reporte_masivo = {
                        "lote_pajuela": pajuela.lote_pajuela,
                        "vacas_por_pajuela": vacas_por_pajuela,
                        "total_escaneadas": len(codigos_rfid),
                        "total_inyectadas": len(inyectadas_ok),
                        "total_rechazadas": len(rechazadas),
                        "pajuelas_descontadas": pajuelas_descontadas,
                        "stock_restante": pajuela.stock,
                        "inyectadas_ok": inyectadas_ok,
                        "rechazadas": rechazadas,
                    }
            except PajuelaSemen.DoesNotExist:
                error_msg = "El lote de pajuela seleccionado no existe."

    vacas_disp_qs = vacas_disponibles().select_related("raza").order_by("codigo_rfid")
    catalogo_vacas = [
        {
            "id": v.id_bovino,
            "rfid": v.codigo_rfid,
            "raza": v.raza.nombre_raza if v.raza else "Angus",
            "estado": v.estado_actual,
        }
        for v in vacas_disp_qs
    ]
    pajuelas_disp = PajuelaSemen.objects.filter(stock__gt=0).select_related("toro", "toro__raza").order_by("lote_pajuela")

    return render(request, "gestor_biologica_monco/inseminacion_masiva.html", {
        "pajuelas": pajuelas_disp,
        "catalogo_vacas_json": json.dumps(catalogo_vacas),
        "total_vacas_disponibles": len(catalogo_vacas),
        "fecha_hoy": timezone.localdate().isoformat(),
        "error": error_msg,
        "reporte": reporte_masivo,
    })


def registro_prenez(request):
    error_msg = None
    success_msg = None
    modo_actual = request.GET.get('modo', 'individual')

    if request.method == 'POST':
        modo_post = request.POST.get('modo_diagnostico', 'individual')
        modo_actual = modo_post

        if modo_post == 'masivo':
            fecha_diagnostico = request.POST.get('fecha_diagnostico') or timezone.localdate().isoformat()
            semanas_default = int(request.POST.get('semanas') or 0)
            resultado_default = request.POST.get('resultado') or 'preñada'
            items_json = request.POST.get('diagnosticos_masivos_json', '[]')

            try:
                lista_items = json.loads(items_json)
            except Exception:
                lista_items = []

            if not lista_items:
                error_msg = "Escanee o agregue al menos una vaca por su código RFID para procesar el diagnóstico masivo."
            else:
                procesados_ok = 0
                errores_lote = []

                for item in lista_items:
                    ins_id = item.get('inseminacion_id')
                    rfid_code = (item.get('rfid') or '').strip().upper()
                    res_item = item.get('resultado') or resultado_default
                    sem_item = int(item.get('semanas') if item.get('semanas') is not None else semanas_default)

                    try:
                        if ins_id:
                            ins = Inseminacion.objects.select_related('vaca').get(pk=ins_id)
                        else:
                            ins = (
                                Inseminacion.objects.select_related('vaca')
                                .filter(vaca__codigo_rfid__iexact=rfid_code)
                                .order_by('-fecha_servicio')
                                .first()
                            )
                        if not ins:
                            errores_lote.append(f"{rfid_code}: Sin registro de inseminación asociado.")
                            continue

                        diag_existente = DiagnosticoGestacion.objects.filter(inseminacion=ins).first()
                        if diag_existente:
                            diag_existente.resultado = res_item
                            diag_existente.semanas = sem_item
                            diag_existente.fecha_diagnostico = fecha_diagnostico
                            diag_existente.clean()
                            diag_existente.save()
                            diag_obj = diag_existente
                        else:
                            nuevo_diag = DiagnosticoGestacion(
                                inseminacion=ins,
                                resultado=res_item,
                                semanas=sem_item,
                                fecha_diagnostico=fecha_diagnostico,
                            )
                            nuevo_diag.clean()
                            nuevo_diag.save()
                            diag_obj = nuevo_diag

                        if res_item == 'preñada':
                            ins.vaca.estado_actual = 'Preñada'
                            ins.vaca.save(update_fields=['estado_actual'])
                        elif res_item == 'vacia':
                            ins.vaca.estado_actual = 'Vacía'
                            ins.vaca.save(update_fields=['estado_actual'])
                        elif res_item == 'mortinato':
                            ins.vaca.estado_actual = 'Vacía'
                            ins.vaca.save(update_fields=['estado_actual'])
                            Parto.objects.update_or_create(
                                diagnostico=diag_obj,
                                defaults={
                                    'cria': None,
                                    'fecha_parto': fecha_diagnostico,
                                    'tipo_parto': 'Mortinato (Fallecido en Parto)',
                                    'observaciones': 'El ternero recién nacido falleció durante el parto (Diagnóstico Masivo RFID).',
                                }
                            )
                        procesados_ok += 1
                    except ValidationError as ve:
                        msg_ve = ve.message if hasattr(ve, 'message') else "; ".join(ve.messages)
                        errores_lote.append(f"{rfid_code or ins_id}: {msg_ve}")
                    except Exception:
                        errores_lote.append(f"{rfid_code or ins_id}: Error al guardar diagnóstico.")

                if procesados_ok > 0:
                    success_msg = f"Diagnóstico masivo por RFID completado: se registraron {procesados_ok} diagnósticos de gestación exitosamente."
                if errores_lote:
                    error_msg = "Observaciones en el lote: " + " | ".join(errores_lote[:5])
        else:
            inseminacion_id = request.POST.get('inseminacion_id')
            resultado = request.POST.get('resultado')
            semanas = request.POST.get('semanas') or 0
            fecha_diagnostico = request.POST.get('fecha_diagnostico')

            try:
                ins = Inseminacion.objects.get(pk=inseminacion_id)
                diag_existente = DiagnosticoGestacion.objects.filter(inseminacion=ins).first()

                if diag_existente:
                    diag_existente.resultado = resultado
                    diag_existente.semanas = semanas
                    diag_existente.fecha_diagnostico = fecha_diagnostico
                    diag_existente.clean()
                    diag_existente.save()
                    diag_obj = diag_existente
                else:
                    nuevo_diag = DiagnosticoGestacion(
                        inseminacion=ins,
                        resultado=resultado,
                        semanas=semanas,
                        fecha_diagnostico=fecha_diagnostico
                    )
                    nuevo_diag.clean() 
                    nuevo_diag.save()
                    diag_obj = nuevo_diag

                if resultado == 'preñada':
                    ins.vaca.estado_actual = 'Preñada'
                    ins.vaca.save(update_fields=['estado_actual'])
                elif resultado == 'vacia':
                    ins.vaca.estado_actual = 'Vacía'
                    ins.vaca.save(update_fields=['estado_actual'])
                elif resultado == 'mortinato':
                    ins.vaca.estado_actual = 'Vacía'
                    ins.vaca.save(update_fields=['estado_actual'])
                    Parto.objects.update_or_create(
                        diagnostico=diag_obj,
                        defaults={
                            'cria': None,
                            'fecha_parto': fecha_diagnostico,
                            'tipo_parto': 'Mortinato (Fallecido en Parto)',
                            'observaciones': 'El ternero recién nacido falleció durante el parto.',
                        }
                    )
                
                success_msg = "Diagnóstico registrado exitosamente. La tabla de inseminaciones y estadísticas han sido actualizadas."
            except ValidationError as e:
                error_msg = e.message
            except Exception as e:
                error_msg = "Error al procesar el registro. Verifique los datos ingresados."

    # Incluye inseminaciones sin diagnóstico y aquellas con preñez activa aún sin parto registrado
    inseminaciones_pendientes = list(
        Inseminacion.objects.select_related('vaca', 'vaca__raza', 'pajuela')
        .filter(
            Q(diagnosticogestacion__isnull=True)
            | Q(diagnosticogestacion__resultado='preñada', diagnosticogestacion__parto__isnull=True)
        )
        .distinct()
        .order_by('-fecha_servicio')
    )

    catalogo_pendientes = [
        {
            "inseminacion_id": ins.id_inseminacion,
            "rfid": ins.vaca.codigo_rfid,
            "raza": ins.vaca.raza.nombre_raza if (ins.vaca and ins.vaca.raza) else "Angus",
            "lote_pajuela": ins.pajuela.lote_pajuela if ins.pajuela else "-",
            "fecha_servicio": ins.fecha_servicio.strftime("%d/%m/%Y"),
            "estado_vaca": ins.vaca.estado_actual,
        }
        for ins in inseminaciones_pendientes
    ]

    return render(request, "gestor_biologica_monco/registro_prenez.html", {
        "inseminaciones_pendientes": inseminaciones_pendientes,
        "catalogo_pendientes_json": json.dumps(catalogo_pendientes),
        "modo_actual": modo_actual,
        "fecha_hoy": timezone.localdate().isoformat(),
        "error": error_msg,
        "success": success_msg
    })

def nuevo_bovino(request):
    sexo_seleccionado = request.GET.get('sexo', 'Hembra') or 'Hembra'
    linaje_seleccionado = request.GET.get('linaje', 'no') or 'no'
    modo_seleccionado = request.GET.get('modo', 'individual') or 'individual'
    error_msg = None
    success_msg = None

    if request.method == 'POST':
        modo_post = request.POST.get('modo_ingreso', modo_seleccionado)
        sexo = request.POST.get('sexo') or sexo_seleccionado
        fecha_nacimiento = request.POST.get('fecha_nacimiento')
        raza_id = request.POST.get('raza_id')
        estado_actual = request.POST.get('estado_actual')
        
        tipo_madre = request.POST.get('tipo_madre', 'vaca_registrada')
        vaca_madre_id = request.POST.get('vaca_madre_id')
        madre_id = request.POST.get('madre_id')

        tipo_padre = request.POST.get('tipo_padre', 'pajuela')
        pajuela_id = request.POST.get('pajuela_id')
        toro_padre_id = request.POST.get('toro_padre_id')
        toro_externo_id = request.POST.get('toro_externo_id')

        try:
            raza = Raza.objects.get(pk=raza_id)
            vaca_madre_obj = None
            toro_padre_obj = None
            madre_ext_obj = None
            pajuela_semen_obj = None

            if linaje_seleccionado == 'si':
                # Procesar Madre (Receptora)
                if tipo_madre == 'vaca_registrada' and vaca_madre_id:
                    vaca_madre_obj = Bovino.objects.get(pk=vaca_madre_id)
                elif tipo_madre == 'madre_externa' and madre_id:
                    if madre_id == 'nueva_externa':
                        madre_ext_obj = Madre.objects.create(
                            sexo='Hembra',
                            fecha_nacimiento=fecha_nacimiento,
                            estado_actual='Vaca Externa'
                        )
                    else:
                        madre_ext_obj = Madre.objects.get(pk=madre_id)

                # Procesar Padre (Reproductor)
                if tipo_padre == 'pajuela' and pajuela_id:
                    pajuela_semen_obj = PajuelaSemen.objects.get(pk=pajuela_id)
                    if pajuela_semen_obj.toro:
                        toro_padre_obj = pajuela_semen_obj.toro
                elif tipo_padre == 'toro_registrado' and toro_padre_id:
                    toro_padre_obj = Bovino.objects.get(pk=toro_padre_id)
                    pajuela_semen_obj = PajuelaSemen.objects.filter(toro=toro_padre_obj).first()
                elif tipo_padre == 'toro_externo' and toro_externo_id:
                    if toro_externo_id == 'nuevo_externo':
                        pajuela_semen_obj = PajuelaSemen.objects.create(
                            toro=None,
                            fecha_extraccion=fecha_nacimiento,
                            stock=0
                        )
                    else:
                        pajuela_semen_obj = PajuelaSemen.objects.get(pk=toro_externo_id)

            if modo_post == 'masivo':
                rfids_masivos_raw = (request.POST.get('rfids_masivos') or '').strip()
                codigos_ingresar = []
                vistos = set()
                for token in rfids_masivos_raw.replace(',', '\n').replace(';', '\n').splitlines():
                    limpio = token.strip().upper()
                    if limpio and limpio not in vistos:
                        vistos.add(limpio)
                        codigos_ingresar.append(limpio)

                if not codigos_ingresar:
                    raise ValidationError("Escanee o ingrese al menos un código RFID en la lista para el ingreso masivo.")

                existentes = set(
                    Bovino.objects.filter(codigo_rfid__in=codigos_ingresar).values_list('codigo_rfid', flat=True)
                )
                nuevos_creados = 0
                for rfid_code in codigos_ingresar:
                    if rfid_code in existentes:
                        continue
                    nb = Bovino.objects.create(
                        codigo_rfid=rfid_code,
                        sexo=sexo,
                        fecha_nacimiento=fecha_nacimiento,
                        raza=raza,
                        estado_actual=estado_actual,
                        madre=madre_ext_obj,
                        pajuela_semen=pajuela_semen_obj,
                    )
                    if vaca_madre_obj:
                        Parentesco.objects.create(bovino=nb, ancestro=vaca_madre_obj, generacion=1, coef_relacion=0.5)
                    if toro_padre_obj:
                        Parentesco.objects.create(bovino=nb, ancestro=toro_padre_obj, generacion=1, coef_relacion=0.5)
                    nuevos_creados += 1

                if nuevos_creados == 0:
                    raise ValidationError("Todos los códigos RFID escaneados ya se encontraban registrados en la base de datos.")

                return redirect('/inicio/')
            else:
                codigo_rfid_manual = (request.POST.get('codigo_rfid_manual') or '').strip().upper()
                nuevo_bov = Bovino(
                    sexo=sexo,
                    fecha_nacimiento=fecha_nacimiento,
                    raza=raza,
                    estado_actual=estado_actual,
                    madre=madre_ext_obj,
                    pajuela_semen=pajuela_semen_obj,
                )
                if codigo_rfid_manual:
                    if Bovino.objects.filter(codigo_rfid=codigo_rfid_manual).exists():
                        raise ValidationError(f"El código RFID '{codigo_rfid_manual}' ya existe en el sistema.")
                    nuevo_bov.codigo_rfid = codigo_rfid_manual

                nuevo_bov.save()

                if vaca_madre_obj:
                    Parentesco.objects.create(
                        bovino=nuevo_bov,
                        ancestro=vaca_madre_obj,
                        generacion=1,
                        coef_relacion=0.5
                    )
                if toro_padre_obj:
                    Parentesco.objects.create(
                        bovino=nuevo_bov,
                        ancestro=toro_padre_obj,
                        generacion=1,
                        coef_relacion=0.5
                    )

                return redirect('/inicio/')
            
        except ValidationError as ve:
            error_msg = ve.message if hasattr(ve, 'message') else "; ".join(ve.messages)
        except Exception:
            error_msg = "Error al guardar el registro en la base de datos. Verifique los campos."

    razas = Raza.objects.all()
    vacas_registradas = Bovino.objects.filter(sexo='Hembra').select_related('raza').order_by('codigo_rfid')[:300] if linaje_seleccionado == 'si' else []
    madres = Madre.objects.all() if linaje_seleccionado == 'si' else []
    pajuelas = PajuelaSemen.objects.select_related('toro').all() if linaje_seleccionado == 'si' else []
    toros_registrados = Bovino.objects.filter(sexo='Macho').select_related('raza').order_by('codigo_rfid') if linaje_seleccionado == 'si' else []
    pajuelas_externas = PajuelaSemen.objects.filter(toro__isnull=True) if linaje_seleccionado == 'si' else []

    return render(request, "gestor_biologica_monco/nuevo_bovino.html", {
        "sexo": sexo_seleccionado,
        "linaje": linaje_seleccionado,
        "modo": modo_seleccionado,
        "fecha_hoy": timezone.localdate().isoformat(),
        "razas": razas,
        "vacas_registradas": vacas_registradas,
        "madres": madres,
        "pajuelas": pajuelas,
        "toros_registrados": toros_registrados,
        "pajuelas_externas": pajuelas_externas,
        "error": error_msg,
        "success": success_msg,
    })