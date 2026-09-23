# Speech — Diapositivas 1–8 (Español)

> Versión mejorada sobre el borrador de Eduardo.  
> Tono: natural y directo, como tú lo escribiste — solo sin huecos ni Spanglish.

---

## Slide 01 — Portada

Buenas tardes. Mi nombre es Eduardo García Díaz, y junto con mis compañeros José Emiliano Carrillo y Cristian Montiel, desarrollamos el proyecto Agentic AI Procurement Agent on Beckn Protocol.

---

## Slide 02 — El Problema

Para entender por qué eso importa, necesitamos hablar del estado actual de las compras empresariales.

Hoy, cuando un comprador necesita algo, el proceso puede verse algo así: el día cero envía la solicitud. Para el día cinco, alguien crea una solicitud de cotización formal — se le llama RFQ — y la manda a los proveedores disponibles. Las cotizaciones llegan días después. Y luego vienen las aprobaciones, que dependen de calendarios y cadenas de autorización. Para el día treinta, si todo salió bien, la orden de compra llega al proveedor.

Treinta días para una procurement order

---

## Slide 03 — Realidad Actual

Otro problema, además de los ciclos lentos, es que las plataformas que dominan el mercado hoy — SAP Ariba, Coupa, Oracle — tienen costos muy altos: cuotas de suscripción, comisiones por transacción, y cargos por habilitar a cada proveedor en la plataforma.

Y aparte del costo, hay otro problema más profundo: son plataformas cerradas. Ellas controlan qué proveedores pueden participar, así que las empresas solo ven a los vendedores que pagaron para estar en esa plataforma. Si un proveedor más barato o más rápido no está registrado ahí, simplemente no existe para el comprador.

---

## Slide 04 — Nuestra Solución

Nuestra solución es un agente de IA que convierte texto en lenguaje natural en una orden de compra confirmada — una PO, por sus siglas en inglés.

El agente descubre proveedores en tiempo real, compara las ofertas, negocia automáticamente para bajar el precio, y cierra la compra con un registro de auditoría completo. Todo sin intervención manual. El resultado es un proceso de compra que pasa de días a segundos.

---

## Slide 05 — Cómo Funciona

¿Cómo funciona? Hay cinco pasos.

**Primero, entender.** El comprador escribe en lenguaje natural lo que necesita. Internamente, el sistema procesa el texto, clasifica la intención, y extrae un objeto estructurado con el tipo de artículo, cantidad, presupuesto y ubicación de entrega.

**Segundo, descubrir.** El sistema envía una petición a través del protocolo Beckn, usando el adaptador ONIX que firma la solicitud y la distribuye a las redes de proveedores conectadas. Las respuestas llegan de forma asíncrona, sin bloquear el sistema.

**Tercero, evaluar.** Con las ofertas recibidas, el modelo RankNet las ranquea comparando precio, velocidad de entrega y riesgo del proveedor. También revisa órdenes pasadas para dar ventaja a proveedores con buen historial.

**Cuarto, negociar.** El agente emite contra-ofertas automáticas para reducir el precio, dentro de los límites de política definidos por la empresa.

**Quinto, confirmar.** Se cierra la orden mediante el handshake completo de Beckn y se registra todo en el ERP.

---

## Slide 06 — Capacidades Empresariales

Estas son algunas características del agente actual

Usa **IA local**, lo que permiite que los datos de compras no salgan del servidor de la empresa. Pero es escalable — puede conectarse a modelos externos como Claude si se necesita más capacidad.

Usa la **versión 2 del protocolo Beckn**, que firma criptográficamente cada transacción y permite conectarse a cualquier proveedor en la red abierta, sin acuerdos bilaterales previos.

Tiene **negociación autónoma**, que reduce los precios de compra de forma automática dentro de los márgenes permitidos

Usa **ML Scoring con RankNet** para rankear proveedores, y **pgvector** para buscar en órdenes pasadas y tomar eso en cuenta al hacer nuevos pedidos — el sistema aprende del historial de la empresa.

Y tiene un **Audit Trail que cumple con SOX 404** — eso es un estándar de cumplimiento financiero que exige poder demostrar y reconstruir cada decisión tomada en el proceso. En nuestro caso, cada evento queda registrado con el razonamiento completo del sistema, no solo el resultado final.

---

## Slide 07 — Impacto de Negocio

Con este sistema, lo que se plantea alcanzar es lo siguiente.

Primero, reducir el **tiempo de ciclo** de días a segundos en órdenes autónomas — eliminando los pasos manuales que hoy hacen lento el proceso.

Segundo, generar un **ahorro de entre cinco y diez por ciento por orden** gracias a la negociación automática, recuperando dinero que hoy se pierde simplemente porque nadie tiene tiempo de negociar cada cotización.

Tercero, abrir el **pool de proveedores** — en lugar de una lista cerrada de vendedores pre-integrados, cualquier proveedor conectado a Beckn estaría disponible desde el primer día.

Y cuarto, que el **cumplimiento normativo** deje de ser trabajo extra — el registro de auditoría existiría automáticamente como parte del proceso, sin proyectos adicionales.

---

## Slide 08 — Diferenciadores

Esta tabla resume por qué esto es diferente a lo que existe hoy.

Las plataformas tradicionales como SAP o Coupa son sistemas cerrados: su catálogo de proveedores es fijo, no tienen LLM integrado, los flujos son manuales, y no aprenden entre compras.

Nosotros hacemos lo contrario en dos puntos clave.

Primero, **protocolo abierto sin acuerdos bilaterales**. Cualquier proveedor que hable Beckn está disponible desde el primer día, sin integración previa, sin cuota de onboarding. Las plataformas tradicionales no pueden ofrecer eso porque su negocio depende precisamente de esos cobros.

Segundo, **autonomía gobernada**. No es un chatbot que hace pedidos. Es un sistema donde el agente tiene autoridad real para negociar y cerrar compras, pero está delimitado por tres capas de gobernanza independientes — reglas del modelo, reglas del servicio, y validación del contrato Beckn — para que nunca pueda exceder la política de la empresa.

Con eso concluye mi parte. Le paso la palabra a [nombre] para continuar con la arquitectura y los resultados medidos.
