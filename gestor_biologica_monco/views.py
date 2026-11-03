import json
from datetime import timedelta
from django.utils import timezone
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.shortcuts import render, redirect
from .models import (
    Bovino, 
    Inseminacion, 
    Parto, 
    AlertaConsanguinidad, 
    PajuelaSemen, 
    Raza, 
    Madre, 
    Usuario, 
    DiagnosticoGestacion, 
    vacas_disponibles,
    Parentesco,
)

def inicio(request):
    today = timezone.localdate()
    
    total_bovinos = Bovino.objects.count()
    
    total_inseminaciones = Inseminacion.objects.filter(
        fecha_servicio__year=today.year,
        fecha_servicio__month=today.month
    ).count()
    
    total_paridas = Parto.objects.filter(fecha_parto__year=today.year).count()
    
    total_alertas = AlertaConsanguinidad.objects.count()
    
    ultimos_ingresos = Bovino.objects.order_by('-id_bovino')[:3]

    hembras = Bovino.objects.filter(sexo='Hembra').count()
    machos = Bovino.objects.filter(sexo='Macho').count()
    
    context = {
        'total_bovinos': total_bovinos,
        'total_inseminaciones': total_inseminaciones,
        'total_paridas': total_paridas,
        'total_alertas': total_alertas,
        'ultimos_ingresos': ultimos_ingresos,
        'chart_labels_meses': json.dumps(['Oct', 'Nov', 'Dic']),
        'chart_data_nacimientos': json.dumps([0, total_paridas, 0]),
        'chart_data_sexos': json.dumps([hembras, machos]),
    }
    
    return render(request, "gestor_biologica_monco/inicio.html", context)


def historial(request):
    filtro = request.GET.get('filtro', 'todo')
    hoy = timezone.localdate()

    inseminaciones = Inseminacion.objects.select_related(
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
    query = request.GET.get('q', '')
    bovino_id = request.GET.get('consultar') or request.GET.get('bovino') or ''
    
    bovinos = Bovino.objects.select_related("raza", "madre", "pajuela_semen__toro").order_by("-id_bovino")
    
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
    if request.method == "POST":
        rut = request.POST.get("rut")
        password = request.POST.get("password")
        
        request.session['usuario_rut'] = rut
        return redirect('gestor_biologica_monco:inicio')
        
    return render(request, "gestor_biologica_monco/login.html")

def inseminacion(request):
    lista_inseminaciones = Inseminacion.objects.select_related('vaca', 'pajuela').all().order_by('-fecha_servicio')
    return render(request, "gestor_biologica_monco/inseminacion.html", {"inseminaciones": lista_inseminaciones})

def pajuelas(request):
    lista_pajuelas = PajuelaSemen.objects.select_related('toro').all()
    return render(request, "gestor_biologica_monco/pajuelas.html", {"pajuelas": lista_pajuelas})

def informes(request):
    return render(request, "gestor_biologica_monco/informes.html")

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

def registro_prenez(request):
    error_msg = None
    success_msg = None

    if request.method == 'POST':
        inseminacion_id = request.POST.get('inseminacion_id')
        resultado = request.POST.get('resultado')
        semanas = request.POST.get('semanas', 0)
        fecha_diagnostico = request.POST.get('fecha_diagnostico')

        try:
            ins = Inseminacion.objects.get(pk=inseminacion_id)
            
            nuevo_diag = DiagnosticoGestacion(
                inseminacion=ins,
                resultado=resultado,
                semanas=semanas,
                fecha_diagnostico=fecha_diagnostico
            )
            nuevo_diag.clean() 
            nuevo_diag.save()

            if resultado == 'preñada':
                ins.vaca.estado_actual = 'Preñada'
                ins.vaca.save(update_fields=['estado_actual'])
            elif resultado == 'vacia':
                ins.vaca.estado_actual = 'Vacía'
                ins.vaca.save(update_fields=['estado_actual'])
            
            success_msg = "Diagnóstico registrado exitosamente. La tabla de inseminaciones ha sido actualizada."
        except ValidationError as e:
            error_msg = e.message
        except Exception as e:
            error_msg = "Error al procesar el registro. Verifique los datos ingresados."

    inseminaciones_pendientes = Inseminacion.objects.filter(
        diagnosticogestacion__isnull=True
    ).order_by('-fecha_servicio')

    return render(request, "gestor_biologica_monco/registro_prenez.html", {
        "inseminaciones_pendientes": inseminaciones_pendientes,
        "error": error_msg,
        "success": success_msg
    })

def nuevo_bovino(request):
    sexo_seleccionado = request.GET.get('sexo', '')
    linaje_seleccionado = request.GET.get('linaje', '')
    error_msg = None

    if request.method == 'POST':
        sexo = request.POST.get('sexo')
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
            nuevo_bov = Bovino(
                sexo=sexo,
                fecha_nacimiento=fecha_nacimiento,
                raza=raza,
                estado_actual=estado_actual
            )
            
            vaca_madre_obj = None
            toro_padre_obj = None

            if linaje_seleccionado == 'si':
                # Procesar Madre (Receptora)
                if tipo_madre == 'vaca_registrada' and vaca_madre_id:
                    vaca_madre_obj = Bovino.objects.get(pk=vaca_madre_id)
                elif tipo_madre == 'madre_externa' and madre_id:
                    if madre_id == 'nueva_externa':
                        nueva_madre_ext = Madre.objects.create(
                            sexo='Hembra',
                            fecha_nacimiento=fecha_nacimiento,
                            estado_actual='Vaca Externa'
                        )
                        nuevo_bov.madre = nueva_madre_ext
                    else:
                        nuevo_bov.madre = Madre.objects.get(pk=madre_id)

                # Procesar Padre (Reproductor)
                if tipo_padre == 'pajuela' and pajuela_id:
                    pajuela_obj = PajuelaSemen.objects.get(pk=pajuela_id)
                    nuevo_bov.pajuela_semen = pajuela_obj
                    if pajuela_obj.toro:
                        toro_padre_obj = pajuela_obj.toro
                elif tipo_padre == 'toro_registrado' and toro_padre_id:
                    toro_padre_obj = Bovino.objects.get(pk=toro_padre_id)
                    pajuela_toro = PajuelaSemen.objects.filter(toro=toro_padre_obj).first()
                    if pajuela_toro:
                        nuevo_bov.pajuela_semen = pajuela_toro
                elif tipo_padre == 'toro_externo' and toro_externo_id:
                    if toro_externo_id == 'nuevo_externo':
                        nueva_pajuela_ext = PajuelaSemen.objects.create(
                            toro=None,
                            fecha_extraccion=fecha_nacimiento,
                            stock=0
                        )
                        nuevo_bov.pajuela_semen = nueva_pajuela_ext
                    else:
                        nuevo_bov.pajuela_semen = PajuelaSemen.objects.get(pk=toro_externo_id)
                
            nuevo_bov.save()

            # Registrar relaciones en Parentesco si provienen de bovinos registrados
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
            
        except Exception as e:
            error_msg = "Error al guardar el registro en la base de datos. Verifique los campos."

    razas = Raza.objects.all()
    vacas_registradas = Bovino.objects.filter(sexo='Hembra').select_related('raza').order_by('codigo_rfid') if linaje_seleccionado == 'si' else []
    madres = Madre.objects.all() if linaje_seleccionado == 'si' else []
    pajuelas = PajuelaSemen.objects.select_related('toro').all() if linaje_seleccionado == 'si' else []
    toros_registrados = Bovino.objects.filter(sexo='Macho').select_related('raza').order_by('codigo_rfid') if linaje_seleccionado == 'si' else []
    pajuelas_externas = PajuelaSemen.objects.filter(toro__isnull=True) if linaje_seleccionado == 'si' else []

    return render(request, "gestor_biologica_monco/nuevo_bovino.html", {
        "sexo": sexo_seleccionado,
        "linaje": linaje_seleccionado,
        "razas": razas,
        "vacas_registradas": vacas_registradas,
        "madres": madres,
        "pajuelas": pajuelas,
        "toros_registrados": toros_registrados,
        "pajuelas_externas": pajuelas_externas,
        "error": error_msg
    })