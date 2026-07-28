# Changelog - Corrección Bug Confirmaciones (3 Julio 2026)

---

## 🐛 Bug Crítico Identificado y Corregido

### **Descripción del Problema**

El sistema eliminaba consumos de `pending_confirmations.json` **ANTES** de confirmar la inserción exitosa en la base de datos. Si la inserción fallaba, el UID quedaba perdido permanentemente y no se podía reintentar.

### **Caso Real que Expuso el Bug**

**UID 989** - Correo AITASA con 20 consumos (Junio 2026):

```
14:31 - Sistema procesa correo → Guarda UID 989 como pendiente ✅
14:31 - Envía confirmación a 5 personas (jmartinez, afargas, lperez, amartorell, iromeu) ✅
14:55 - Ivan Romeu responde "OK" 
        → confirm_and_remove_selective() ELIMINA UID 989 ✅
        → Intenta insertar en BD ❌ ERROR: duplicate key violates unique constraint
        → UID 989 perdido para siempre ❌
21:07 - Jordi Martinez responde "OK" (6 horas después)
        → Error: "Sin consumos pendientes para UID 989" (ya fue eliminado)
```

**Error en log de producción:**
```
2026-07-03 14:55:18  ERROR  duplicate key value violates unique constraint "ux_ite_consums_datarect_data_idtag_tipus"
```

---

## ✅ Solución Implementada

### **Archivos Modificados**

1. **`pending_confirmations.py`** - Nuevas funciones para separar lectura y eliminación
2. **`main.py`** - Flujo transaccional: eliminar solo después de éxito en BD

---

## 📝 Cambios en `pending_confirmations.py`

### **Nuevas Funciones Agregadas**

#### 1. `get_pending_consumptions(uid, line_numbers)`
```python
def get_pending_consumptions(uid: str, line_numbers: list[int] | None = None) -> list[dict] | None:
    """
    Obtiene consumos pendientes SIN eliminarlos del archivo.
    Útil para verificar datos antes de confirmar inserción en BD.
    
    Returns:
        Lista de consumptions dict, o None si el UID no existe
    """
```

**Propósito:** Leer datos de pendientes sin modificar el archivo. Permite verificar antes de comprometer.

#### 2. `remove_pending(uid, line_numbers)`
```python
def remove_pending(uid: str, line_numbers: list[int] | None = None) -> bool:
    """
    Elimina consumos pendientes del archivo (después de inserción exitosa en BD).
    
    Returns:
        True si se eliminó algo, False si el UID no existía
    """
```

**Propósito:** Eliminar de pendientes **SOLO después** de confirmar inserción exitosa.

#### 3. `confirm_and_remove_selective()` - Marcada como DEPRECADA
```python
def confirm_and_remove_selective(uid: str, line_numbers: list[int] | None = None) -> list[dict] | None:
    """
    DEPRECADO: Usar get_pending_consumptions() + remove_pending() para transaccionalidad.
    """
```

**Mantiene backward compatibility** pero el nuevo flujo no la usa.

---

## 🔄 Cambios en `main.py` (líneas ~320-410)

### **Flujo ANTERIOR (Bugueado)**

```python
# ❌ Elimina INMEDIATAMENTE
consumptions_data = confirm_and_remove_selective(original_uid, line_numbers)

# Reconstruir objetos
consumptions = [...]

# Intentar insertar
try:
    save_consumptions(...)
except Exception as db_exc:
    # ❌ Ya es tarde - UID eliminado permanentemente
    logger.error("Error al guardar en BD")
    continue
```

**Problema:** `confirm_and_remove_selective()` elimina el UID del JSON ANTES de intentar insertar en BD.

---

### **Flujo NUEVO (Corregido)**

```python
# ✅ PASO 1: Obtener datos SIN eliminar
from pending_confirmations import get_pending_consumptions, remove_pending

consumptions_data = get_pending_consumptions(original_uid, line_numbers)

if not consumptions_data:
    # Error: no hay pendientes
    continue

# Reconstruir objetos Consumption
consumptions = [...]

# ✅ PASO 2: Intentar inserción en BD (puede fallar)
db_not_found: list[str] = []
if config.db.enabled:
    try:
        _, db_not_found = save_consumptions(...)
    except Exception as db_exc:
        logger.error("Error al guardar en BD [%s]: %s", uid, db_exc)
        logger.warning(
            "UID [%s] mantenido en pendientes para reintentar después de solucionar el error",
            original_uid,
        )
        # ✅ NO eliminamos de pendientes - se puede reintentar
        failed_messages.append(...)
        reader.move_message(uid, config.email.folder_errors)
        errors += 1
        continue

# Verificar empresas no encontradas
if db_not_found:
    logger.warning("Empresas no identificadas: %s", db_not_found)
    logger.warning(
        "UID [%s] mantenido en pendientes para reintentar después de corregir empresas",
        original_uid,
    )
    # ✅ NO eliminamos de pendientes - se puede corregir y reintentar
    failed_messages.append(...)
    reader.move_message(uid, config.email.folder_errors)
    errors += 1
    continue

# ✅ PASO 3: SOLO si todo fue exitoso, eliminar de pendientes
remove_pending(original_uid, line_numbers)
logger.info(
    "✓ UID [%s]: Consumos confirmados e insertados correctamente en BD",
    original_uid,
)

# Mover confirmación a carpeta OK
reader.move_message(uid, config.email.folder_confirmed)
results.extend(consumptions)
```

**Ventajas:**
- **Transaccionalidad**: Solo elimina si operación completa es exitosa
- **Recuperabilidad**: Si falla BD, datos quedan pendientes para reintentar
- **Trazabilidad**: Logs claros indican cuándo se mantiene pendiente y por qué

---

## 📊 Comparación de Comportamientos

| Escenario | Antes (Bug) | Después (Corregido) |
|-----------|-------------|---------------------|
| **Inserción exitosa** | ✅ Elimina de pendientes | ✅ Elimina de pendientes |
| **Error BD (duplicate key)** | ❌ Elimina de pendientes | ✅ Mantiene en pendientes |
| **Empresa no encontrada** | ❌ Elimina de pendientes | ✅ Mantiene en pendientes |
| **Excepción inesperada** | ❌ Elimina de pendientes | ✅ Mantiene en pendientes |
| **Reintento después de error** | ❌ Imposible (perdido) | ✅ Posible (datos conservados) |

---

## 🔍 Nuevos Mensajes de Log

### **Cuando hay error pero se mantienen pendientes:**
```
⚠️  UID [989] mantenido en pendientes para reintentar después de solucionar el error
```

### **Cuando se elimina exitosamente:**
```
✓ UID [989]: Consumos confirmados e insertados correctamente en BD
```

### **Cuando se elimina de pendientes:**
```
INFO  UID [989] eliminado completamente de pendientes
INFO  UID [989]: eliminados 3 consumos, quedan 7 pendientes
```

---

## 📂 Configuración de Producción Modificada

### **Archivo:** `\\serversql4\C\nifi-2.0.0-M3\python\scripts\mail2LLM\config.xml`

**Cambio temporal realizado (luego revertido):**

Durante el análisis del problema, se configuró temporalmente para enviar notificaciones solo a `jmartinez@ccaait.cat` para evitar spam durante el reprocesamiento.

**Estado final (restaurado):**
```xml
<to>jmartinez@ccaait.cat,afargas@ccaait.cat,lperez@ccaait.cat,amartorell@ccaait.cat,iromeu@ccaait.cat</to>
<include_original_senders>afargas@ccaait.cat,lperez@ccaait.cat,amartorell@ccaait.cat,iromeu@ccaait.cat</include_original_senders>
```

---

## 📋 Estado de Pendientes en Producción

**Archivo:** `\\serversql4\C\nifi-2.0.0-M3\python\scripts\mail2LLM\pending_confirmations.json`

**Solo 2 UIDs pendientes (1 Junio 2026):**

- **UID 645**: Messer El Morell - Mayo 2026 (1,093,780 m³) 🚨 **Valor sospechoso**
- **UID 646**: Messer El Morell - Mayo 2026 (1,093,780 m³) 🚨 **Duplicado**

**Problema detectado:** El LLM probablemente extrajo la lectura del contador en vez del consumo (valor demasiado alto).

**Los 10 pendientes antiguos del entorno local NO están en producción** (ya fueron procesados).

---

## 🧪 Testing Recomendado

### **Para verificar la corrección:**

1. **Simular error de BD:**
   ```python
   # Modificar temporalmente save_consumptions() para lanzar excepción
   raise Exception("Test error")
   ```

2. **Ejecutar main.py y confirmar un consumo**
   - Verificar que el UID permanece en `pending_confirmations.json`
   - Revisar logs: debe aparecer "mantenido en pendientes"

3. **Corregir el error y volver a ejecutar**
   - Ahora SÍ debe insertar correctamente
   - El UID debe eliminarse de pendientes
   - Log debe mostrar "✓ Consumos confirmados e insertados correctamente"

---

## 🔜 Próximos Pasos Pendientes

### **1. Desplegar corrección a producción**

**Archivos a copiar:**
```
main.py → \\serversql4\C\nifi-2.0.0-M3\python\scripts\mail2LLM\main.py
pending_confirmations.py → \\serversql4\C\nifi-2.0.0-M3\python\scripts\mail2LLM\pending_confirmations.py
```

**Recomendación:** Hacer backup antes de sobrescribir.

### **2. Revisar pendientes sospechosos (645, 646)**

Los valores de Messer (1M m³) son claramente erróneos. Opciones:
- Revisar el correo original para ver qué extrajo mal el LLM
- Eliminar manualmente de pending_confirmations.json
- Buscar el email original en carpeta `0_Processats` y reprocesar

### **3. Problema de contadores múltiples (identificado pero NO resuelto)**

**Situación:** Algunos consorciados tienen 2+ contadores con el mismo `id_bcentral` (CLxxxxx) pero diferentes tags de destino.

**Código actual:** Siempre usa `LIMIT 1` en la query de `ite_comptadors`, devolviendo siempre el mismo contador.

**Solución pendiente:** Necesita análisis de:
- ¿Qué diferencia los correos de cada contador? (remitente, asunto, texto)
- ¿La tabla `ite_comptadors` tiene campos para discriminar?
- ¿Necesitamos tabla de mapeo manual?

**Archivos afectados:**
- `db/repository.py` línea 132-140: función `_get_idtag_from_consorciat()`

---

## 📌 Resumen Ejecutivo

**Cambio realizado:** Implementación de flujo transaccional para confirmaciones

**Archivos modificados:** `pending_confirmations.py`, `main.py`

**Estado:** ✅ Implementado en desarrollo, ⏳ Pendiente desplegar a producción

**Impacto:** Evita pérdida de datos cuando falla inserción en BD

**Backward compatibility:** ✅ Mantenida (funciones antiguas siguen disponibles)

**Testing:** ⏳ Pendiente en entorno de desarrollo antes de producción

---

## 📞 Contactos para Notificaciones

**Email de confirmaciones (producción):**
- jmartinez@ccaait.cat
- afargas@ccaait.cat
- lperez@ccaait.cat
- amartorell@ccaait.cat
- iromeu@ccaait.cat

**Include original senders:**
- afargas@ccaait.cat
- lperez@ccaait.cat
- amartorell@ccaait.cat
- iromeu@ccaait.cat

---

**Fecha:** 3 Julio 2026  
**Autor:** Sesión de desarrollo con GitHub Copilot  
**Versión del sistema:** mail2LLM en producción (Apache NIFI cada 5 minutos)
