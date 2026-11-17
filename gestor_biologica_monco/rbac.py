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


RUTS_ADMIN_PROTEGIDOS = ("1111111-1", "22127234-K")


def asegurar_usuarios_iniciales():
    """Garantiza que la cuenta principal de Administrador (1.111.111-1) esté siempre creada y aprobada."""
    try:
        if not Usuario.objects.exists():
            Usuario.objects.create(
                rut="1.111.111-1",
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
        else:
            ruts_existentes = {normalizar_rut(u.rut): u for u in Usuario.objects.all()}
            # Si se borró accidentalmente el RUT administrador 1.111.111-1, restaurarlo
            if "1111111-1" not in ruts_existentes:
                Usuario.objects.create(
                    rut="1.111.111-1",
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

            # Asegurar que el RUT de Administrador (1.111.111-1) esté siempre habilitado como Admin
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

    return None


def contexto_rbac(request):
    usuario = obtener_usuario_activo(request)
    if not usuario:
        return {
            "rol_actual": "pendiente",
            "rol_titulo": "Sin Sesión",
            "usuario_nombre_activo": "Invitado",
            "usuario_rut_activo": "",
            "usuario_email_activo": "",
            "es_admin": False,
            "aprobado_por_admin": False,
            "puede_inicio": False,
            "puede_rendimiento": False,
            "puede_inseminacion": False,
            "puede_linaje": False,
            "puede_pajuelas": False,
            "puede_informes": False,
            "puede_bovino_nuevo": False,
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
    Middleware que verifica que el usuario haya iniciado sesión, que esté aprobado por el Administrador
    y que cuente con permiso para el módulo solicitado.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path or "/"

        # Al entrar a la raíz (127.0.0.1:8000/), enviar siempre a la pantalla de Iniciar Sesión
        if path == "/":
            return redirect("/login/?logout=1")

        if (
            path.startswith("/login")
            or path.startswith("/esperando-permisos")
            or path.startswith("/static")
            or path.startswith("/admin")
        ):
            return self.get_response(request)

        usuario = obtener_usuario_activo(request)
        if not usuario:
            return redirect("/login/")

        ctx = contexto_rbac(request)

        # Si el usuario aún está esperando aprobación del Administrador, enviarlo a la sala de espera
        if not ctx["aprobado_por_admin"] or ctx["rol_actual"] == "pendiente":
            return redirect("/esperando-permisos/")

        # Si el usuario navega a cualquier módulo distinto de /usuarios, bloquear automáticamente el panel de Roles y Permisos
        if not path.startswith("/usuarios") and not path.startswith("/static"):
            request.session.pop("usuarios_desbloqueado", None)

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
