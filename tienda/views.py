from django.shortcuts import render, redirect
from .models import ClienteB2C
from django.contrib import messages
from .models import ClienteB2B
from .models import Producto
from django.utils import timezone
from .models import CotizacionEmpresa
from django.template.loader import get_template
from django.http import HttpResponse
from xhtml2pdf import pisa
from .models import DetalleCotizacionEmpresa
from django.shortcuts import get_object_or_404
from django.contrib.auth.decorators import login_required
from tienda.models import Producto
from django.views.decorators.csrf import csrf_exempt
from .models import CompraCliente, DetalleCompraCliente
from django.db.models import Q
from transbank.webpay.webpay_plus.transaction import Transaction
from transbank.common.options import WebpayOptions
from transbank.common.integration_type import IntegrationType
from django.conf import settings
from django.urls import reverse
from django.core.paginator import Paginator
import requests 
import json
from django.http import JsonResponse
import math
import re
from django.core.validators import validate_email
from django.core.exceptions import ValidationError

def home(request):
    productos_destacados = Producto.objects.all()[:12]
    return render(request, 'tienda/home.html', {'productos_destacados': productos_destacados})

def registro(request):
    if request.method == 'POST':
        nombre = request.POST.get('nombre')
        apellido = request.POST.get('apellido')
        rut = request.POST.get('rut')
        telefono = request.POST.get('telefono')
        correo = request.POST.get('correo')
        contrasena = request.POST.get('contrasena')

        # Validación de campos vacíos
        if not all([nombre, apellido, rut, telefono, correo, contrasena]):
            return render(request, 'registrousuario.html', {'error': 'Todos los campos son obligatorios'})

        # Validación RUT chileno
        if not validar_rut_chileno(rut):
            return render(request, 'registrousuario.html', {'error': 'El RUT no es válido'})

        # Validación teléfono chileno
        if not re.match(r'^(\+569\d{8}|[2-9]\d{7,8})$', telefono):
            return render(request, 'registrousuario.html', {'error': 'El teléfono debe ser chileno (ej: +56912345678 o fijo)'})

        # Validación correo
        try:
            validate_email(correo)
            if not (correo.endswith('.com') or correo.endswith('.cl')):
                raise ValidationError("Extensión no válida")
        except ValidationError:
            return render(request, 'registrousuario.html', {'error': 'El correo no es válido'})

        # Contraseña
        if len(contrasena) < 6:
            return render(request, 'registrousuario.html', {'error': 'La contraseña debe tener al menos 6 caracteres'})

        # Correo ya registrado
        if ClienteB2C.objects.filter(correo=correo).exists():
            return render(request, 'tienda/registrousuario.html', {'error': 'El correo ya está registrado'})

        # Guardar usuario
        ClienteB2C.objects.create(
            nombre=nombre,
            apellido=apellido,
            rut=rut,
            telefono=telefono,
            correo=correo,
            contrasena=contrasena
        )
        return redirect('home')

    return render(request, 'tienda/registrousuario.html')
 
def validar_rut_chileno(rut):
    rut = rut.replace(".", "").replace("-", "")
    if len(rut) < 8 or not rut[:-1].isdigit():
        return False
    cuerpo = rut[:-1]
    dv = rut[-1].upper()

    suma = 0
    multiplo = 2
    for c in reversed(cuerpo):
        suma += int(c) * multiplo
        multiplo = 9 if multiplo == 2 else multiplo - 1
    resto = suma % 11
    digito = 'K' if (11 - resto == 10) else str((11 - resto) % 11)

    return dv == digito

def login(request):
    if request.method == 'POST':
        correo = request.POST.get('correo')
        contrasena = request.POST.get('contrasena')

        try:
            cliente = ClienteB2C.objects.get(correo=correo, contrasena=contrasena)
            request.session['usuario_id'] = cliente.id_cliente  # <- cambio aquí
            request.session['usuario_nombre'] = cliente.nombre
            return redirect('home')
        except ClienteB2C.DoesNotExist:
            return render(request, 'home.html', {'error': 'Correo o contraseña incorrectos'})

    return redirect('home')

def login_cliente(request):
    if request.method == 'POST':
        correo = request.POST.get('correo')
        contrasena = request.POST.get('contrasena')

        try:
            cliente = ClienteB2C.objects.get(correo=correo, contrasena=contrasena)
            request.session['usuario_id'] = cliente.id_cliente
            request.session['usuario_nombre'] = cliente.nombre
            return redirect('home')
        except ClienteB2C.DoesNotExist:
            return render(request, 'tienda/logincliente.html', {'error': 'Correo o contraseña incorrectos'})

    return render(request, 'tienda/logincliente.html')


def logout(request):
    request.session.flush()
    return redirect('home')


@csrf_exempt
def agregar_al_carrito(request):
    if request.method == "POST":
        producto_id = request.POST.get("producto_id")
        cantidad = int(request.POST.get("cantidad", 1))

        carrito = request.session.get("carrito_b2c", {})
        carrito[producto_id] = carrito.get(producto_id, 0) + cantidad
        request.session["carrito_b2c"] = carrito
        request.session.modified = True

        return redirect("home") 
    return redirect("home")

def carrito_cliente(request):
    if 'usuario_id' not in request.session:
        return redirect('logincliente')

    cliente = ClienteB2C.objects.get(id_cliente=request.session['usuario_id'])
    carrito = request.session.get('carrito_b2c', {})
    items = []
    total = 0

    for id_producto, cantidad in carrito.items():
        producto = Producto.objects.get(id=id_producto)
        subtotal = producto.precio * cantidad
        total += subtotal
        items.append({
            'producto': producto,
            'cantidad': cantidad,
            'subtotal': subtotal
        })

    comunas_disponibles = obtener_codigos_comunas_chilexpress()
    requiere_envio = request.session.get('requiere_envio', False)
    costo_envio = 0

    # ✅ Aquí calculamos costo si hay comuna guardada en sesión
    if requiere_envio and request.session.get('comuna_envio'):
        comuna_codigo = request.session['comuna_envio']
        costo_envio = obtener_costo_envio_chilexpress(comuna_codigo)

    return render(request, 'tienda/carrito_cliente.html', {
        'items': items,
        'total': total,
        'cliente': cliente,
        'comunas': comunas_disponibles,
        'costo_envio': costo_envio,
        'requiere_envio': requiere_envio
    })



def catalogo_b2c(request):
    categoria = request.GET.get('categoria')
    marcas_seleccionadas = request.GET.getlist('marca')
    query = request.GET.get('q')  # 🔍 búsqueda

    productos = Producto.objects.all()

    if categoria:
        productos = productos.filter(categoria=categoria)

    if marcas_seleccionadas:
        productos = productos.filter(marca__in=marcas_seleccionadas)

    if query:
        productos = productos.filter(nombre__icontains=query)

    categorias = Producto.objects.values_list('categoria', flat=True).distinct()
    marcas = Producto.objects.values_list('marca', flat=True).distinct()

    paginator = Paginator(productos, 18)  # 18 productos por página (6 columnas x 3 filas)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'productos': page_obj,
        'page_obj': page_obj,
        'categorias': categorias,
        'marcas': marcas,
        'categoria_seleccionada': categoria,
        'marcas_seleccionadas': marcas_seleccionadas,
        'query': query  
    }

    return render(request, 'tienda/catalogo_b2c.html', context)


def catalogo_por_marca(request, nombre):
    productos = Producto.objects.filter(marca=nombre)
    categorias = Producto.objects.values_list('categoria', flat=True).distinct()
    marcas = Producto.objects.values_list('marca', flat=True).distinct()

    return render(request, 'tienda/catalogo_b2c.html', {
        'productos': productos,
        'categorias': categorias,
        'marcas': marcas,
        'marca_actual': nombre,
        'marcas_seleccionadas': [nombre],
    })

def simular_pago(request):
    if request.method == 'POST':
        total = request.POST.get('total')
        request.session['carrito_b2c'] = {}
        messages.success(request, f"¡Pago exitoso por ${total}! Se ha enviado tu boleta al correo registrado.")
        return redirect('home')
    return redirect('carrito_cliente')

def generar_compra(request):
    if 'usuario_id' not in request.session:
        return redirect('logincliente')

    cliente = get_object_or_404(ClienteB2C, id_cliente=request.session['usuario_id'])
    carrito = request.session.get('carrito_b2c', {})
    productos = Producto.objects.filter(id__in=carrito.keys())

    total = 0
    for producto in productos:
        cantidad = carrito[str(producto.id)]
        if producto.stock < cantidad:
            messages.error(request, f"Stock insuficiente para '{producto.nombre}'.")
            return redirect('carrito_b2c')  

    compra = CompraCliente.objects.create(
    cliente=cliente,
    total=0,
    estado='Pagado',
    fecha=timezone.now()
    )


    for producto in productos:
        cantidad = carrito[str(producto.id)]
        subtotal = producto.precio * cantidad
        total += subtotal

        DetalleCompraCliente.objects.create(
            compra=compra,
            producto=producto,
            cantidad=cantidad,
            precio_unitario=producto.precio,
            subtotal=subtotal
        )

        producto.stock -= cantidad
        producto.save()

    compra.total = total
    compra.save()

    # Limpiar carrito
    request.session['carrito_b2c'] = {}
    request.session.modified = True

    messages.success(request, "¡Compra realizada con éxito!")
    return redirect('perfil_cliente')

def perfil_cliente(request):
    if 'usuario_id' not in request.session:
        return redirect('home')

    try:
        cliente = ClienteB2C.objects.get(id_cliente=request.session['usuario_id'])
        compras = CompraCliente.objects.filter(cliente=cliente).order_by('-fecha')
    except ClienteB2C.DoesNotExist:
        cliente = None
        compras = []

    return render(request, 'tienda/perfil_cliente.html', {
        'cliente': cliente,
        'compras': compras
    })


def procesar_compra_cliente(request):
    if 'usuario_id' not in request.session:
        return redirect('logincliente')

    cliente = get_object_or_404(ClienteB2C, id_cliente=request.session['usuario_id'])
    carrito = request.session.get('carrito_b2c', {})
    productos = Producto.objects.filter(id__in=carrito.keys())

    total = 0
    for producto in productos:
        cantidad = carrito[str(producto.id)]
        if producto.stock < cantidad:
            messages.error(request, f"No hay stock suficiente para '{producto.nombre}'")
            return redirect('carrito_cliente')

    compra = CompraCliente.objects.create(
        cliente=cliente,
        total=0,
        estado='Pagado',
        fecha=timezone.now()
    )

    for producto in productos:
        cantidad = carrito[str(producto.id)]
        subtotal = producto.precio * cantidad
        total += subtotal

        DetalleCompraCliente.objects.create(
            compra=compra,
            producto=producto,
            cantidad=cantidad,
            precio_unitario=producto.precio,
            subtotal=subtotal
        )

        producto.stock -= cantidad
        producto.save()

    compra.total = total
    compra.save()

    request.session['carrito_b2c'] = {}
    request.session.modified = True

    messages.success(request, "Compra realizada exitosamente.")
    return redirect('perfil_cliente')

def descargar_boleta(request, id):
    from .models import CompraCliente, DetalleCompraCliente  # por si no estaban importados
    compra = get_object_or_404(CompraCliente, id=id)
    detalles = DetalleCompraCliente.objects.filter(compra=compra)

    # Obtener costo de envío desde sesión (si existe)
    costo_envio = request.session.get('costo_envio', 0)
    subtotal_sin_envio = compra.total - costo_envio if costo_envio else compra.total

    template_path = 'tienda/boleta_pdf.html'
    context = {
        'compra': compra,
        'detalles': detalles,
        'subtotal_sin_envio': subtotal_sin_envio,
        'costo_envio': costo_envio
    }

    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="boleta_{compra.id}.pdf"'
    html = get_template(template_path).render(context)

    pisa_status = pisa.CreatePDF(html, dest=response)
    if pisa_status.err:
        return HttpResponse('Error al generar boleta', status=500)
    return response

def detalle_producto(request, id):
    producto = get_object_or_404(Producto, id=id)
    return render(request, 'tienda/detalleproducto.html', {'producto': producto})

def iniciar_pago_webpay(request):
    if 'usuario_id' not in request.session:
        return redirect('logincliente')

    requiere_envio = request.POST.get('requiere_envio') == 'si'
    comuna_codigo = request.POST.get('comuna') if requiere_envio else None
    direccion = request.POST.get('direccion') if requiere_envio else None

    carrito = request.session.get('carrito_b2c', {})
    productos = Producto.objects.filter(id__in=carrito.keys())

    total = 0
    for producto in productos:
        cantidad = carrito[str(producto.id)]
        total += producto.precio * cantidad

    # Aquí se agrega el cálculo simulado del costo de envío
    costo_envio = 0
    if requiere_envio:
        peso_total = sum([(producto.peso or 0) * carrito[str(producto.id)] for producto in productos])
        costo_envio = 5990
        if peso_total > 1:
            kilos_extras = math.ceil(peso_total - 1)
            costo_envio += int(round(5990 * 0.05 * kilos_extras))

    total_final = total + costo_envio

    # Guardar en sesión para usar en la boleta
    request.session['requiere_envio'] = requiere_envio
    request.session['comuna_envio'] = comuna_codigo
    request.session['direccion_envio'] = direccion
    request.session['costo_envio'] = costo_envio
    request.session['total_final'] = total_final

    # Crear transacción con Webpay
    transaction = Transaction()
    response = transaction.create(
        buy_order=f"orden-{request.session['usuario_id']}",
        session_id=str(request.session['usuario_id']),
        amount=total_final,  # ✅ aquí se envía el total CON envío incluido
        return_url=request.build_absolute_uri(reverse('webpay_return'))
    )

    return render(request, 'tienda/redireccion_webpay.html', {
        'webpay_url': response.url,
        'token': response.token
    })


@csrf_exempt
def webpay_return(request):
    token = request.POST.get("token_ws")
    if not token:
        return HttpResponse("Token no recibido", status=400)

    try:
        # Configuración global del SDK (según tu versión)
        Transaction.commerce_code = settings.TRANSBANK_COMMERCE_CODE
        Transaction.api_key = settings.TRANSBANK_API_KEY
        Transaction.integration_type = IntegrationType.TEST

        transaction = Transaction()
        response = transaction.commit(token)

        if response.status == 'AUTHORIZED':
            return redirect('procesar_compra_exitosa')
        else:
            messages.error(request, f"Pago rechazado: {response.status}")
            return redirect('carrito_cliente')

    except Exception as e:
        return HttpResponse(f"Error al procesar el pago: {str(e)}", status=500)
    
def procesar_compra_exitosa(request):
    if 'usuario_id' not in request.session:
        return redirect('logincliente')

    cliente = get_object_or_404(ClienteB2C, id_cliente=request.session['usuario_id'])
    carrito = request.session.get('carrito_b2c', {})
    productos = Producto.objects.filter(id__in=carrito.keys())

    total = 0
    errores_stock = []

    for producto in productos:
        cantidad = carrito[str(producto.id)]
        if producto.stock < cantidad:
            errores_stock.append(producto.nombre)

    if errores_stock:
        messages.error(request, f"Sin stock para: {', '.join(errores_stock)}")
        return redirect('carrito_cliente')

    compra = CompraCliente.objects.create(
        cliente=cliente,
        total=0,
        estado='Pagado',
        fecha=timezone.now()
    )

    for producto in productos:
        cantidad = carrito[str(producto.id)]
        subtotal = producto.precio * cantidad
        total += subtotal

        DetalleCompraCliente.objects.create(
            compra=compra,
            producto=producto,
            cantidad=cantidad,
            precio_unitario=producto.precio,
            subtotal=subtotal
        )

        producto.stock -= cantidad
        producto.save()

    compra.total = total
    compra.save()

    request.session['carrito_b2c'] = {}
    request.session.modified = True

    messages.success(request, "¡Compra realizada con éxito!")
    return redirect('perfil_cliente')


def categoria(request, categoria_nombre):
    productos_filtrados = Producto.objects.filter(categoria__iexact=categoria_nombre)
    return render(request, 'tienda/categoria.html', {
        'productos': productos_filtrados,
        'categoria': categoria_nombre
    })


def mostrar_informacion(request, seccion):
    contenido_info = {
        "ayuda-cliente": {
            "titulo": "Ayuda al Cliente",
            "contenido": """
            <p>¿Tienes dudas? Aquí tienes algunas formas en que podemos ayudarte:</p>
            <ul>
                <li>Revisa nuestras <strong>Preguntas Frecuentes</strong>.</li>
                <li>Contáctanos al correo: <a href="mailto:contacto@autoparts.cl">contacto@autoparts.cl</a></li>
                <li>Llámamos al <strong>+56 9 1234 5678</strong></li>
                <li>Horario de atención: Lunes a Viernes de 09:00 a 18:00 hrs</li>
            </ul>
            """
        },
        "politica-despacho": {
            "titulo": "Política de Despacho",
            "contenido": """
            <p>Nos comprometemos a entregar tus productos de forma rápida y segura:</p>
            <ul>
                <li>Despachamos en un plazo de 24 a 72 horas hábiles.</li>
                <li>Trabajamos con <strong>Chilexpress</strong> y <strong>Bluexpress</strong>.</li>
                <li>El seguimiento se envía automáticamente al correo tras el pago.</li>
                <li>El costo de envío se calcula en el checkout, según tu región.</li>
            </ul>
            """
        },
        "bases-promociones": {
            "titulo": "Bases Promociones Vigentes",
            "contenido": """
            <p>Consulta las condiciones de nuestras campañas promocionales:</p>
            <ul>
                <li>Las promociones no son acumulables con otros descuentos.</li>
                <li>Aplican solo a productos seleccionados y hasta agotar stock.</li>
                <li>Fechas de validez: desde el 01/07/2025 hasta el 15/07/2025.</li>
                <li>Promociones sujetas a cambios sin previo aviso.</li>
            </ul>
            """
        },
        "servicios-tienda": {
            "titulo": "Servicios en Tienda",
            "contenido": """
            <p>En nuestras sucursales Autoparts puedes acceder a los siguientes servicios:</p>
            <ul>
                <li>Instalación de baterías y ampolletas.</li>
                <li>Revisión gratuita de frenos y aceite.</li>
                <li>Recomendación de repuestos compatibles según tu vehículo.</li>
                <li>Asesoría presencial por parte de nuestros técnicos.</li>
            </ul>
            """
        },
        "seguimiento": {
            "titulo": "Seguimiento de Pedido",
            "contenido": """
            <p>Puedes hacer seguimiento de tu pedido de estas formas:</p>
            <ul>
                <li>Ve al historial en tu cuenta si estás registrado.</li>
                <li>Consulta el código de seguimiento que te enviamos por correo.</li>
                <li>O contáctanos con tu número de orden a <a href="mailto:despachos@autoparts.cl">despachos@autoparts.cl</a></li>
            </ul>
            """
        },
        "modos-entrega": {
            "titulo": "Modos de Entrega",
            "contenido": """
            <p>Contamos con diferentes opciones de entrega para tu comodidad:</p>
            <ul>
                <li><strong>Retiro en tienda:</strong> disponible en 1 hora hábil posterior a la compra.</li>
                <li><strong>Envío a domicilio:</strong> entregas a todo Chile vía Chilexpress o Bluexpress.</li>
                <li>Elige la opción al momento de pagar y revisa costos y tiempos estimados.</li>
            </ul>
            """
        },
        "sobre-cyberday": {
    "titulo": "CyberDay",
    "contenido": """
    <p><strong>CyberDay</strong> es uno de los eventos de descuentos más importantes del año en Autoparts. Durante estos días, podrás acceder a ofertas únicas en repuestos, lubricantes, accesorios y mucho más.</p>
    <ul>
        <li>Descuentos de hasta un 50% en productos seleccionados.</li>
        <li>Ofertas válidas solo por 72 horas o hasta agotar stock.</li>
        <li>Promociones exclusivas para compras online.</li>
        <li>Medios de pago habilitados: Webpay, Mercado Pago y transferencias.</li>
    </ul>
    <p>¡Prepárate y aprovecha las mejores oportunidades para mantener tu vehículo en óptimas condiciones!</p>
    """
},
"sobre-cybermonday": {
    "titulo": "CyberMonday",
    "contenido": """
    <p><strong>CyberMonday</strong> en Autoparts es el evento ideal para quienes buscan equipar su auto con productos de calidad a precios rebajados.</p>
    <ul>
        <li>Envíos gratis en compras superiores a $50.000.</li>
        <li>Acceso anticipado para clientes registrados.</li>
        <li>Ofertas flash renovadas cada 12 horas.</li>
        <li>Stock garantizado y reposición constante durante el evento.</li>
    </ul>
    <p>No pierdas la oportunidad de renovar tus repuestos y accesorios con grandes descuentos.</p>
    """
},
"sobre-blackfriday": {
    "titulo": "Black Friday",
    "contenido": """
    <p>En <strong>Black Friday</strong>, Autoparts lanza sus precios más bajos del año. Es el momento perfecto para adquirir todo lo que necesitas para tu auto, antes de las vacaciones o el verano.</p>
    <ul>
        <li>Combos especiales y kits de mantenimiento con descuentos extra.</li>
        <li>Ofertas exclusivas en productos premium: Philips, Bosch, Valeo y más.</li>
        <li>Precios válidos solo por 48 horas.</li>
        <li>Todos los pedidos incluyen seguimiento y embalaje seguro.</li>
    </ul>
    <p>¡Conecta tu pasión por los autos con la oportunidad perfecta de ahorrar!</p>
    """
},
"sobre-mayoristas": {
    "titulo": "AutoParts Mayoristas",
    "contenido": """
    <p>En Autoparts, ofrecemos atención especializada para <strong>mayoristas, talleres y flotas</strong> que buscan soluciones confiables y precios competitivos.</p>
    <ul>
        <li>Catálogo exclusivo con productos técnicos y de alta rotación.</li>
        <li>Asesoría personalizada para compras por volumen.</li>
        <li>Opciones de pago flexibles y descuentos por cantidad.</li>
        <li>Facturación directa, despacho programado y soporte postventa.</li>
    </ul>
    <p>Contáctanos si eres empresa, mecánico independiente o distribuidor y accede a beneficios únicos.</p>
    """
},
"sobre-tienda": {
    "titulo": "Nuestra Tienda",
    "contenido": """
    <p>Visítanos en nuestra sucursal de <strong>Diez de Julio 711, Santiago Centro</strong>, donde encontrarás repuestos, lubricantes, baterías y más.</p>
    <ul>
        <li>Asesoría personalizada por expertos.</li>
        <li>Instalación básica gratuita de baterías.</li>
        <li>Horario: Lunes a Sábado de 9:30 a 18:30 hrs.</li>
    </ul>
    <p>Te esperamos con las mejores marcas del mercado y atención confiable.</p>
    """
}


    }

    datos = contenido_info.get(seccion, {
        "titulo": "Información no disponible",
        "contenido": "La sección que estás buscando no fue encontrada."
    })

    return render(request, 'tienda/informacion.html', datos)
""" Mayorista """
def registro_mayorista(request):
    if request.method == 'POST':
        nombre_empresa = request.POST['nombre_empresa']
        rut_empresa = request.POST['rut']
        direccion = request.POST['direccion']
        telefono = request.POST['telefono']
        correo_empresa = request.POST['correo']
        contrasena = request.POST['contrasena']

        if ClienteB2B.objects.filter(correo_empresa=correo_empresa).exists():
            messages.error(request, 'El correo ya está registrado')
            return redirect('registromayorista')

        ClienteB2B.objects.create(
            nombre_empresa=nombre_empresa,
            rut_empresa=rut_empresa,
            direccion=direccion,
            telefono=telefono,
            correo_empresa=correo_empresa,
            contrasena=contrasena
        )

        messages.success(request, '¡Te registraste en Autoparts! Ahora inicia sesión.')
        return redirect('loginmayorista')

    return render(request, 'tienda/registromayorista.html')

def login_mayorista(request):
    if request.method == 'POST':
        correo = request.POST['correo']
        contrasena = request.POST['contrasena']

        try:
            empresa = ClienteB2B.objects.get(correo_empresa=correo, contrasena=contrasena)
            request.session['mayorista_id'] = empresa.id_cliente_b2b
            request.session['mayorista_nombre'] = empresa.nombre_empresa
            return redirect('homemayorista')
        except ClienteB2B.DoesNotExist:
            return render(request, 'tienda/loginmayorista.html', {'error': 'Credenciales inválidas'})

    return render(request, 'tienda/loginmayorista.html')

def perfil_empresa(request):
    if 'mayorista_id' not in request.session:
        return redirect('home')

    try:
        empresa = ClienteB2B.objects.get(id_cliente_b2b=request.session['mayorista_id'])
    except ClienteB2B.DoesNotExist:
        return redirect('home')

    return render(request, 'tienda/perfil_empresa.html', {
        'empresa': empresa
    })

def catalogo_empresa(request):
    productos = Producto.objects.filter(stock__gt=0)  

    # Filtro por búsqueda
    query = request.GET.get("q")
    if query:
        productos = productos.filter(nombre__icontains=query)

    # Filtro por categoría
    categoria = request.GET.get("categoria")
    if categoria:
        productos = productos.filter(categoria=categoria)

    # Filtro por marcas (si vienen como checkbox múltiple)
    marcas = request.GET.getlist("marca")
    if marcas:
        productos = productos.filter(marca__in=marcas)

    # Agrega precio con descuento
    for producto in productos:
        producto.precio_con_descuento = int(producto.precio * 0.85)

    # Listas únicas para filtros
    categorias = Producto.objects.values_list('categoria', flat=True).distinct()
    marcas_carousel = Producto.objects.values_list('marca', flat=True).distinct()

    return render(request, 'tienda/catalogo_empresa.html', {
        'productos': productos,
        'categorias': categorias,
        'marcas_carousel': marcas_carousel,
        'marcas_seleccionadas': marcas,
    })

def detalle_producto_empresa(request, id):
    producto = get_object_or_404(Producto, id=id)
    precio_original = int(producto.precio)
    precio_empresa = int(precio_original * 0.85)

    return render(request, 'tienda/detalle_producto_empresa.html', {
        'producto': producto,
        'precio_original': precio_original,
        'precio_empresa': precio_empresa,
    })

def agregar_al_carrito_empresa(request):
    if request.method == 'POST':
        producto_id = str(request.POST.get('producto_id'))
        cantidad = int(request.POST.get('cantidad', 1))

        carrito = request.session.get('carrito_empresa', {})

        if producto_id in carrito:
            carrito[producto_id] += cantidad
        else:
            carrito[producto_id] = cantidad

        request.session['carrito_empresa'] = carrito
        return redirect('catalogo_empresa')

def generar_cotizacion_empresa(request):
    if 'mayorista_id' not in request.session:
        return redirect('loginmayorista')

    cliente = get_object_or_404(ClienteB2B, id_cliente_b2b=request.session['mayorista_id'])
    carrito = request.session.get('carrito_empresa', {})
    productos = Producto.objects.filter(id__in=carrito.keys())

    total = 0
    detalles = []

    # Validar stock
    for producto in productos:
        cantidad = carrito[str(producto.id)]
        if producto.stock < cantidad:
            messages.error(request, f"El producto '{producto.nombre}' no tiene suficiente stock.")
            return redirect('cotizacion_empresa')

    # Crear cotización
    cotizacion = CotizacionEmpresa.objects.create(
        cliente=cliente,
        total=0  # se actualiza después
    )

    for producto in productos:
        cantidad = carrito[str(producto.id)]
        precio_unitario = int(producto.precio * 0.85)
        subtotal = cantidad * precio_unitario
        total += subtotal

        DetalleCotizacionEmpresa.objects.create(
            cotizacion=cotizacion,
            producto=producto,
            cantidad=cantidad,
            precio_unitario=precio_unitario,
            subtotal=subtotal
        )

        # Restar stock
        producto.stock -= cantidad
        producto.save()

    # Actualizar total en cotización
    cotizacion.total = total
    cotizacion.save()

    # Vaciar carrito
    request.session['carrito_empresa'] = {}
    request.session.modified = True

    messages.success(request, "Cotización generada correctamente.")
    return redirect('mis_cotizaciones_empresa')


def cotizacion_empresa(request):
    # Verificar si está logueado como mayorista
    if 'mayorista_id' not in request.session:
        return redirect('loginmayorista')

    cliente = get_object_or_404(ClienteB2B, id_cliente_b2b=request.session['mayorista_id'])

    carrito = request.session.get('carrito_empresa', {})
    productos = Producto.objects.filter(id__in=carrito.keys())

    items = []
    total = 0
    for producto in productos:
        cantidad = carrito[str(producto.id)]
        precio_unitario = int(producto.precio * 0.85)
        subtotal = cantidad * precio_unitario
        total += subtotal
        items.append({
            'id': producto.id,
            'nombre': producto.nombre,
            'precio': precio_unitario,
            'cantidad': cantidad,
            'subtotal': subtotal
        })

    return render(request, 'tienda/cotizacion_empresa.html', {
        'carrito': items,
        'total': total,
        'cliente': cliente
    })

def mis_cotizaciones_empresa(request):
    if 'mayorista_id' not in request.session:
        return redirect('loginmayorista')

    cliente_id = request.session['mayorista_id']
    cotizaciones = CotizacionEmpresa.objects.filter(cliente_id=cliente_id).order_by('-fecha')

    return render(request, 'tienda/mis_cotizaciones_empresa.html', {
        'cotizaciones': cotizaciones
    })

def descargar_cotizacion_pdf(request, id):
    cotizacion = CotizacionEmpresa.objects.get(id=id)
    detalles = DetalleCotizacionEmpresa.objects.filter(cotizacion=cotizacion)

    template_path = 'tienda/cotizacion_pdf.html'
    context = {
        'cotizacion': cotizacion,
        'detalles': detalles
    }

    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="cotizacion_{cotizacion.id}.pdf"'
    template = get_template(template_path)
    html = template.render(context)

    pisa_status = pisa.CreatePDF(html, dest=response)
    if pisa_status.err:
        return HttpResponse('Error al generar PDF', status=500)
    return response

def logout_mayorista(request):
    request.session.flush()
    return redirect('home')

def homemayorista(request):
    return render(request, 'tienda/homemayorista.html')

""" vistas api chileexpress """
from django.http import JsonResponse, HttpResponse

def ver_regiones_disponibles(request):
    url = "http://testservices.wschilexpress.com/georeference/api/v1/regions"
    headers = {
        "Ocp-Apim-Subscription-Key": "782c134e544d425ebee52f49da58ed44"
    }

    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        try:
            regiones = response.json()
            return JsonResponse(regiones, safe=False)
        except Exception as e:
            return HttpResponse(f"Error al parsear JSON: {e}")
    else:
        return HttpResponse(f"Error HTTP: {response.status_code} - {response.text}")


def obtener_codigos_comunas_chilexpress():
    url = "http://testservices.wschilexpress.com/georeference/api/v1.0/coverage-areas?RegionCode=RM&type=0"
    headers = {
        "Ocp-Apim-Subscription-Key": "782c134e544d425ebee52f49da58ed44"
    }

    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        data = response.json()
        comunas_raw = data.get("coverageAreas", [])

        # Filtrar y eliminar duplicados por countyName + regionName (protegido con .get)
        comunas_unicas = {}
        for c in comunas_raw:
            nombre = c.get('countyName', 'Desconocido')
            region = c.get('regionName', 'Desconocido')
            key = (nombre, region)

            if key not in comunas_unicas:
                comunas_unicas[key] = c

        comunas = sorted(comunas_unicas.values(), key=lambda x: x.get('countyName', ''))
        print("✅ Comunas únicas (seguras):", len(comunas))
        return comunas

    print("❌ Error al obtener comunas:", response.status_code, response.text)
    return []


def obtener_costo_envio_chilexpress(comuna_destino_codigo, peso_kg=1):
    url = "http://testservices.wschilexpress.com/rating/api/v1/rates/courier"
    headers = {
        "Ocp-Apim-Subscription-Key": "8bceb0c7f1e4448a9980a5047447285e",
        "Content-Type": "application/json"
    }

    payload = {
        "originCountyCode": "QN",  # Santiago
        "destinationCountyCode": comuna_destino_codigo,
        "package": {
            "weight": peso_kg,
            "height": 10,
            "width": 10,
            "length": 10
        },
        "productType": 3,
        "deliveryTime": 1
    }

    response = requests.post(url, headers=headers, json=payload)
    if response.status_code == 200:
        data = response.json()
        if isinstance(data, list) and 'totalValue' in data[0]:
            return int(data[0]['totalValue'])
    return 0




def ver_comunas_chilexpress(request):
    comunas = obtener_codigos_comunas_chilexpress()
    html = "<h2>Listado de Comunas con cobertura (tipo=A)</h2><ul>"
    for c in comunas:
        html += f"<li>{c['countyName']} ({c['countyCode']}) - {c['regionName']}</li>"
    html += "</ul>"
    return HttpResponse(html)

@csrf_exempt
def obtener_costo_envio_carrito(request):
    try:
        body = json.loads(request.body)
        comuna_codigo = body.get('comuna')

        if not comuna_codigo:
            return JsonResponse({'error': 'Comuna no especificada'}, status=400)

        carrito = request.session.get('carrito_b2c', {})
        if not carrito:
            return JsonResponse({'error': 'Carrito vacío'}, status=400)

        productos = Producto.objects.filter(id__in=carrito.keys())

        peso_total = 0.0
        for producto in productos:
            cantidad = carrito[str(producto.id)]
            peso_total += (float(producto.peso) or 0) * cantidad

        # 🔢 Reglas
        costo_base = 5990
        if peso_total <= 1:
            costo_envio = costo_base
        else:
            kilos_extras = math.ceil(peso_total - 1)
            aumento = costo_base * 0.05 * kilos_extras
            costo_envio = int(round(costo_base + aumento))

        return JsonResponse({'costo_envio': costo_envio})

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)
