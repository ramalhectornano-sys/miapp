# Estado de búsqueda, ubicaciones y kilómetros — 0.5.0

La actualización implementa investigación web general Tavily/Groq y geografía de Argentina. **Código probado con proveedores simulados no significa comprobado en la cuenta real.** La búsqueda de chofer en Rincón de los Sauces a 100 km sigue pendiente de ejecución y comprobantes reales. No se acreditaron ofertas para enlazar aquí.

| Requisito | Estado del código 0.5.0 y límite |
| --- | --- |
| Investigación general | Consultas por puesto, sinónimos, lugar, empresas, consultoras y publicaciones. LinkedIn/Computrabajo son adicionales. |
| Presupuesto | 6 consultas normalmente, máximo 12; hasta 24 resultados y 6 páginas públicas. No cubre todo Internet. |
| País/provincia/localidad | Identidad y centroides GeoRef para Argentina. Otros países requieren otro proveedor. |
| Localidades homónimas | Elegir coincidencia comprobada y volver a validar al guardar. |
| Radio | Localidad (0), opciones habituales y radio personalizado entero de 0 a 1000 km. |
| Distancia | Haversine aérea aproximada entre centroides. Distancia por ruta y dirección exacta no implementadas. |
| Fuera del radio | Se excluye si la localidad publicada se pudo verificar; ubicación dudosa queda pendiente. |
| Provincia completa | No implementada como modo administrativo independiente; un radio no equivale a toda una provincia. |
| Enlaces originales | Lector público acotado con DNS, redirecciones y robots. Páginas restringidas/no accesibles quedan pendientes. |
| Fechas y requisitos | Se conservan y muestran cuando hay evidencia; no se inventan los ausentes. |
| Historial web | Migración 007, API y pantalla con consultas, horas, fuentes, recibos y errores privados por usuario. |
| Prueba real Tavily/Groq | Intentada en Actions; preflight bloqueado por claves ausentes allí. Cero llamadas a proveedores; no aprobada. |
| Gmail | Vinculación confirmada por el usuario; entrega real todavía no acreditada. |
| Teléfono apagado | Worker/programador preparados; requieren configuración, habilitación y ejecución registrada. |
| Enviar a hallazgos web | La investigación general no verifica destinatarios. Solo fuentes específicas verificadas y consentimiento pueden habilitar correo. |

## Instalar y comprobar

1. Aplicar solamente [migración 007](../supabase/migrations/202610140007_web_research_and_locations.sql) si 001–006 ya están instaladas. No repetir el instalador inicial ni una migración ya aplicada.
2. Desplegar backend 0.5.0 de trabajo-ya-real. En Render Environment, cambiar explícitamente WEB_SEARCH_MAX_QUERIES a **6** si el Blueprint anterior dejó 2; Manual Deploy no modifica ese valor existente. Ver [BUSQUEDA_WEB](BUSQUEDA_WEB.md).
3. Usar la APK 0.5.0 cuando su publicación esté confirmada en [APK_REAL](APK_REAL.md).
4. Para la prueba real, guardar WEB_SEARCH_API_KEY y AI_API_KEY en [Actions Secrets](https://github.com/ramalhectornano-sys/miapp/settings/secrets/actions) y ejecutar [el workflow real](https://github.com/ramalhectornano-sys/miapp/actions/workflows/trabajo-ya-web-real-test.yml). Ver [PRUEBA_WEB_REAL](PRUEBA_WEB_REAL.md).
5. Configurar y comprobar el worker para ejecuciones periódicas. Mantener MAIL_SEND_ENABLED=false hasta una prueba de envío controlada y autorización específica.

Una coordenada oficial confirma una localidad, no la ubicación del empleo. El puesto debe citar su lugar; el país o ciudad de la búsqueda no sirven para fingir cercanía. El radio puede cruzar provincias. El catálogo y las localidades investigadas tienen límites que se informan.

Render Free no ejecuta el worker continuo. GitHub Actions sirve para pruebas con demoras y cuotas. Cloud Run Jobs/Scheduler o un servidor supervisado pueden generar cargos. IA, búsqueda, base de datos y geocodificación tienen condiciones propias. Esta actualización no activa servicios pagos.

## Comprobación de entrega

CI [38744160825](https://github.com/ramalhectornano-sys/miapp/actions/runs/38744160825)
aprobó 403 pruebas backend, 52 móviles, TypeScript, siete migraciones y 29 cloud.
La prueba real [38744160735](https://github.com/ramalhectornano-sys/miapp/actions/runs/38744160735)
falló antes de consultar proveedores por secretos de Actions ausentes; no
comprobó ubicaciones remotas ni produjo ofertas reales acreditadas.
