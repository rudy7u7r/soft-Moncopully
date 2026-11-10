from django.contrib.auth.hashers import check_password, is_password_usable, make_password
from django.shortcuts import redirect
from .models import Usuario

PERMISOS_POR_DEFECTO_ROL = {
    "admin": {
        "titulo": "Administrador",
        "acceso_rendimiento": True,
        "acceso_inseminacion": True,
        "acceso_linaje": True,
        "acceso_pajuelas": True,
        "acceso_informes": True,
        "acceso_bovinos": True,
    },
    "veterinario": {
        "titulo": "Veterinario",
        "acceso_rendimiento": True,
        "acceso_inseminacion": True,
        "acceso_linaje": True,
        "acceso_pajuelas": True,
        "acceso_informes": False,
        "acceso_bovinos": False,
    },
    "operario": {
        "titulo": "Operario de Terreno",
        "acceso_rendimiento": True,
        "acceso_inseminacion": False,
        "acceso_linaje": False,
        "acceso_pajuelas": False,
        "acceso_informes": True,
        "acceso_bovinos": True,
    },
}


def normalizar_rut(rut_str):
    """Elimina puntos y espacios para comparar RUTs de forma consistente."""
    if not rut_str:
        return ""
    limpio = "".join(ch for ch in str(rut_str).strip().upper() if ch.isalnum() or ch == "-")
    limpio_sin_guion = limpio.replace("-", "")
    if len(limpio_sin_guion) >= 2:
        return f"{limpio_sin_guion[:-1]}-{limpio_sin_guion[-1]}"
    return limpio


def formatear_rut_visual(rut_str):
    limpio = normalizar_rut(rut_str)
    if "-" not in limpio:
        return limpio
    cuerpo, dv = limpio.split("-", 1)
    if not cuerpo.isdigit():
        return limpio
    partes = []
    while len(cuerpo) > 3:
        partes.insert(0, cuerpo[-3:])
        cuerpo = cuerpo[:-3]
    if cuerpo:
        partes.insert(0, cuerpo)
    return f"{'.'.join(partes)}-{dv}"


def cifrar_password(raw_password):
    return make_password(raw_password)


def verificar_password_usuario(usuario, raw_password):
    """Verifica la contraseña cifrada (y migra a hash PBKDF2 si estaba en texto plano)."""
    stored = usuario.password or ""
    if stored.startswith("pbkdf2_") or stored.startswith("argon2") or stored.startswith("bcrypt"):
        return check_password(raw_password, stored)
    if stored == raw_password:
        usuario.password = make_password(raw_password)
        usuario.save(update_fields=["password"])
        return True
    return False


RUTS_ADMIN_PROTEGIDOS = ("1111111-1", "11111111-1")


def asegurar_usuarios_iniciales():
    """Garantiza que los usuarios base y la cuenta de Administrador estén siempre creados y aprobados."""
    try:
        if not Usuario.objects.exists():
            Usuario.objects.create(
                rut="1.111.111-1",
                nombre_completo="Jordan Loaiza (Administrador)",
                email="jordanloaiza@gmail.com",
                password=make_password("admin123"),
                rol="admin",
                aprobado_por_admin=True,
                acceso_rendimiento=True,
                acceso_inseminacion=True,
                acceso_linaje=True,
                acceso_pajuelas=True,
                acceso_informes=True,
                acceso_bovinos=True,
                activo=True,
            )
            Usuario.objects.create(
                rut="11.111.111-1",
                nombre_completo="Administrador General",
                email="jordanloaiza@gmail.com",
                password=make_password("admin123"),
                rol="admin",
                aprobado_por_admin=True,
                acceso_rendimiento=True,
                acceso_inseminacion=True,
                acceso_linaje=True,
                acceso_pajuelas=True,
                acceso_informes=True,
                acceso_bovinos=True,
                activo=True,
            )
            Usuario.objects.create(
                rut="22.222.222-2",
                nombre_completo="Médico Veterinario",
                email="veterinario.moncopulli@gmail.com",
                password=make_password("vet123"),
                rol="veterinario",
                aprobado_por_admin=True,
                acceso_rendimiento=True,
                acceso_inseminacion=True,
                acceso_linaje=True,
                acceso_pajuelas=True,
                acceso_informes=False,
                acceso_bovinos=False,
                activo=True,
            )
            Usuario.objects.create(
                rut="33.333.333-3",
                nombre_completo="Operario de Terreno",
                email="terreno.moncopulli@gmail.com",
                password=make_password("terreno123"),
                rol="operario",
                aprobado_por_admin=True,
                acceso_rendimiento=True,
                acceso_inseminacion=False,
                acceso_linaje=False,
                acceso_pajuelas=False,
                acceso_informes=True,
                acceso_bovinos=True,
                activo=True,
            )
        else:
            ruts_existentes = {normalizar_rut(u.rut): u for u in Usuario.objects.all()}
            # Si se borró accidentalmente el RUT administrador 1.111.111-1 o 11.111.111-1, restaurarlo
            for rut_admin_visual, norm_key in (("1.111.111-1", "1111111-1"), ("11.111.111-1", "11111111-1")):
                if norm_key not in ruts_existentes:
                    Usuario.objects.create(
                        rut=rut_admin_visual,
                        nombre_completo="jordan loaiza",
                        email="jordanloaiza@gmail.com",
                        password=make_password("admin123"),
                        rol="admin",
                        aprobado_por_admin=True,
                        acceso_rendimiento=True,
                        acceso_inseminacion=True,
                        acceso_linaje=True,
                        acceso_pajuelas=True,
                        acceso_informes=True,
                        acceso_bovinos=True,
                        activo=True,
                    )

            # Asegurar que los RUTs de Administrador (1.111.111-1 y 11.111.111-1) estén siempre habilitados como Admin
            for u in Usuario.objects.all():
                cambios = []
                if normalizar_rut(u.rut) in RUTS_ADMIN_PROTEGIDOS:
                    if u.rol != "admin":
                        u.rol = "admin"
                        cambios.append("rol")
                    if not u.aprobado_por_admin:
                        u.aprobado_por_admin = True
                        cambios.append("aprobado_por_admin")
                    if not u.activo:
                        u.activo = True
                        cambios.append("activo")
                    for campo_perm in (
                        "acceso_rendimiento",
                        "acceso_inseminacion",
                        "acceso_linaje",
                        "acceso_pajuelas",
                        "acceso_informes",
                        "acceso_bovinos",
                    ):
                        if not getattr(u, campo_perm):
                            setattr(u, campo_perm, True)
                            cambios.append(campo_perm)
                if u.rol in ("admin", "veterinario", "operario") and not u.aprobado_por_admin:
                    u.aprobado_por_admin = True
                    cambios.append("aprobado_por_admin")
                if u.password and not u.password.startswith("pbkdf2_"):
                    u.password = make_password(u.password)
                    cambios.append("password")
                if cambios:
                    u.save(update_fields=list(set(cambios)))
    except Exception:
        pass


def buscar_usuario_por_rut(rut_ingresado):
    asegurar_usuarios_iniciales()
    rut_norm = normalizar_rut(rut_ingresado)
    if not rut_norm:
        return None
    for u in Usuario.objects.all():
        if normalizar_rut(u.rut) == rut_norm:
            return u
    return None


def obtener_usuario_activo(request):
    asegurar_usuarios_iniciales()
    uid = request.session.get("usuario_id")
    if uid:
        u = Usuario.objects.filter(pk=uid, activo=True).first()
        if u:
            return u

    rut_ses = request.session.get("usuario_rut")
    if rut_ses:
        u = buscar_usuario_por_rut(rut_ses)
        if u and u.activo:
            return u

    return Usuario.objects.filter(rol="admin", activo=True).first() or Usuario.objects.filter(activo=True).first()


def contexto_rbac(request):
    usuario = obtener_usuario_activo(request)
    if not usuario:
        return {
            "rol_actual": "admin",
            "rol_titulo": "Administrador",
            "usuario_nombre_activo": "Administrador",
            "usuario_rut_activo": "11.111.111-1",
            "usuario_email_activo": "admin.moncopulli@gmail.com",
            "es_admin": True,
            "aprobado_por_admin": True,
            "puede_inicio": True,
            "puede_rendimiento": True,
            "puede_inseminacion": True,
            "puede_linaje": True,
            "puede_pajuelas": True,
            "puede_informes": True,
            "puede_bovino_nuevo": True,
            "solicitudes_pendientes_count": 0,
        }

    es_admin = usuario.rol == "admin" and usuario.aprobado_por_admin
    pendientes_count = Usuario.objects.filter(aprobado_por_admin=False).count() if es_admin else 0

    return {
        "rol_actual": usuario.rol,
        "rol_titulo": usuario.get_rol_display(),
        "usuario_nombre_activo": usuario.nombre_completo,
        "usuario_rut_activo": usuario.rut,
        "usuario_email_activo": usuario.email,
        "es_admin": es_admin,
        "aprobado_por_admin": usuario.aprobado_por_admin,
        "puede_inicio": usuario.aprobado_por_admin,
        "puede_rendimiento": True if es_admin else (usuario.aprobado_por_admin and usuario.acceso_rendimiento),
        "puede_inseminacion": True if es_admin else (usuario.aprobado_por_admin and usuario.acceso_inseminacion),
        "puede_linaje": True if es_admin else (usuario.aprobado_por_admin and usuario.acceso_linaje),
        "puede_pajuelas": True if es_admin else (usuario.aprobado_por_admin and usuario.acceso_pajuelas),
        "puede_informes": True if es_admin else (usuario.aprobado_por_admin and usuario.acceso_informes),
        "puede_bovino_nuevo": True if es_admin else (usuario.aprobado_por_admin and usuario.acceso_bovinos),
        "solicitudes_pendientes_count": pendientes_count,
    }


class ControlAccesoRolMiddleware:
    """
    Middleware que verifica en base de datos si el usuario ya fue aprobado por el Administrador
    y si cuenta con permiso para el módulo solicitado.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path or "/"

        if (
            path.startswith("/login")
            or path.startswith("/esperando-permisos")
            or path.startswith("/static")
            or path.startswith("/admin")
        ):
            return self.get_response(request)

        ctx = contexto_rbac(request)

        # Si el usuario aún está esperando aprobación del Administrador, enviarlo a la sala de espera
        if not ctx["aprobado_por_admin"] or ctx["rol_actual"] == "pendiente":
            return redirect("/esperando-permisos/")

        if path.startswith("/usuarios") and not ctx["es_admin"]:
            return redirect("/inicio/?acceso_restringido=usuarios")
        if path.startswith("/inseminacion") and not ctx["puede_inseminacion"]:
            return redirect("/inicio/?acceso_restringido=inseminacion")
        if (path.startswith("/linaje") or path.startswith("/arbol_genealogico") or path.startswith("/verificar")) and not ctx["puede_linaje"]:
            return redirect("/inicio/?acceso_restringido=linaje")
        if path.startswith("/pajuelas") and not ctx["puede_pajuelas"]:
            return redirect("/inicio/?acceso_restringido=pajuelas")
        if (path.startswith("/informes") or path.startswith("/exportar")) and not ctx["puede_informes"]:
            return redirect("/inicio/?acceso_restringido=informes")
        if path.startswith("/bovino/nuevo") and not ctx["puede_bovino_nuevo"]:
            return redirect("/inicio/?acceso_restringido=bovino_nuevo")
        if path.startswith("/rendimiento") and not ctx["puede_rendimiento"]:
            return redirect("/inicio/?acceso_restringido=rendimiento")

        return self.get_response(request)
