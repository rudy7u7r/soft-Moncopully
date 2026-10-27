from django.utils import timezone
from django.shortcuts import render

from .models import AlertaConsanguinidad, Bovino, Inseminacion, Parto


def inicio(request):
    today = timezone.localdate()
    bovinos = Bovino.objects.select_related("raza").order_by("-id_bovino")
    return render(
        request,
        "gestor_biologica_monco/inicio.html",
        {
            "bovinos": bovinos[:3],
            "bovinos_count": bovinos.count(),
            "inseminaciones_count": Inseminacion.objects.filter(
                fecha_servicio__year=today.year,
                fecha_servicio__month=today.month,
            ).count(),
            "alertas_count": AlertaConsanguinidad.objects.count(),
        },
    )


def historial(request):
    partos = Parto.objects.select_related(
        "cria",
        "diagnostico__inseminacion__vaca",
        "diagnostico__inseminacion__pajuela",
    ).order_by("-fecha_parto")
    return render(request, "gestor_biologica_monco/historial.html", {"partos": partos})


def linaje(request):
    bovinos = Bovino.objects.select_related("raza").order_by("-id_bovino")
    return render(request, "gestor_biologica_monco/linaje.html", {"bovinos": bovinos})


def verificar(request):
    bovino_id = request.GET.get("bovino", "")
    bovino = None
    if bovino_id.isdecimal():
        bovino = Bovino.objects.filter(pk=int(bovino_id)).first()

    return render(
        request,
        "gestor_biologica_monco/verificar.html",
        {"bovino": bovino},
    )


def login(request):
    return render(request, "gestor_biologica_monco/login.html")
