"""Literal UIA insertion, bound to an unchanged field; never clipboard or key replay."""
import time


def field_snapshot(field):
    current = field
    for _ in range(16):
        if current.element_info.element.CurrentIsPassword:
            raise ValueError('Password fields cannot receive dictation.')
        if current.element_info.control_type == 'Window':
            break
        current = current.parent()
        if current is None:
            break
    else:
        raise ValueError('The text field privacy state could not be verified.')
    if not field.is_visible() or not field.is_enabled() or field.iface_value.CurrentIsReadOnly:
        raise ValueError('Choose an enabled, writable text field.')
    value = field.get_value()
    if not isinstance(value, str) or len(value) > 50000:
        raise ValueError('This field is too large for verified dictation.')
    before, after = value, ''
    # Use the caret/selection when TextPattern and ValuePattern agree. Otherwise
    # appending is explicit in the capture status, never an inferred cursor position.
    mode = 'append'
    try:
        document = field.iface_text.DocumentRange
        selections = field.iface_text.GetSelection()
        if selections.Length == 1 and document.GetText(-1) == value:
            selected = selections.GetElement(0)
            prefix, suffix = document.Clone(), document.Clone()
            prefix.MoveEndpointByRange(1, selected, 0)
            suffix.MoveEndpointByRange(0, selected, 1)
            before, after = prefix.GetText(-1), suffix.GetText(-1)
            if before + selected.GetText(-1) + after != value:
                raise ValueError('Selection did not match the document.')
            mode = 'selection'
    except Exception:
        before, after = value, ''
    return {'id': list(field.element_info.runtime_id), 'value': value,
            'before': before, 'after': after, 'mode': mode}


def eligible_fields(window):
    result = []
    for field in window.descendants(depth=10)[:300]:
        if field.element_info.control_type not in {'Edit', 'Document'}:
            continue
        try:
            field_snapshot(field)
            result.append(field)
        except Exception:
            continue
    return result


def prepare(target):
    import pythoncom
    from pywinauto import Desktop
    from .automation_worker import validate
    pythoncom.CoInitialize()
    try:
        validate(target)
        window = Desktop(backend='uia').window(handle=target['hwnd']).wrapper_object()
        fields = eligible_fields(window)
        focused = [field for field in fields if field.has_keyboard_focus()]
        candidates = focused or fields
        if len(candidates) != 1:
            raise ValueError('Click the intended writable text field first, then start dictation again.')
        field = candidates[0]
        if not focused:
            window.set_focus()
            field.set_focus()
        validate(target, foreground=True)
        return {'target': target, 'field': field_snapshot(field), 'deadline': time.monotonic() + 90}
    finally:
        pythoncom.CoUninitialize()


def apply_to_field(field, binding, text):
    if not isinstance(text, str) or not text or len(text) > 8000 or '\x00' in text:
        raise ValueError('Dictation must contain between 1 and 8,000 text characters.')
    current = field_snapshot(field)
    if current != binding:
        raise ValueError('The field, content or selection changed. Nothing was inserted.')
    expected = binding['before'] + text + binding['after']
    if len(expected) > 50000:
        raise ValueError('The resulting field would be too large.')
    field.iface_value.SetValue(expected)
    if field.get_value() != expected:
        raise ValueError('Insertion was attempted but could not be confirmed. Check the field; it will not be retried.')
    return 'Dictation inserted and verified. Nothing was submitted.'


def insert(binding, text):
    import pythoncom
    from pywinauto import Desktop
    from .automation_worker import validate
    if time.monotonic() > binding['deadline']:
        raise ValueError('The dictation target expired. Start dictation again.')
    pythoncom.CoInitialize()
    try:
        target = binding['target']
        validate(target, foreground=True)
        window = Desktop(backend='uia').window(handle=target['hwnd']).wrapper_object()
        fields = [field for field in eligible_fields(window)
                  if list(field.element_info.runtime_id) == binding['field']['id']]
        if len(fields) != 1 or not fields[0].has_keyboard_focus():
            raise ValueError('The selected text field changed or lost focus. Nothing was inserted.')
        validate(target, foreground=True)
        result = apply_to_field(fields[0], binding['field'], text)
        validate(target, foreground=True)
        return result
    finally:
        pythoncom.CoUninitialize()
