# Инструкции для агента

## Локальная память

### История исправленных ошибок

- **bot/api/schemas/master_schemas.py:** Исправлены 66 ошибок типа "No overloads for Field match the provided arguments" путем замены `example` на `examples` и корректировки значений.

### Текущий план

1. **Проанализировать ошибки из файла `pyright_summary.txt`.** (Выполнено)
2. **Создать файл `agnets.md` для отслеживания прогресса.** (Выполнено, файл уже существовал)
3. **Исправить ошибки в файле `bot/api/schemas/master_schemas.py` (66 ошибок).** (Выполнено)
4. **Обновить `agnets.md` и сделать коммит.** (Текущий шаг)
5. **Исправить ошибки в файле `tests/game/managers/test_party_manager.py` (65 ошибок).**
    - Исправить ошибки типа `Cannot assign to attribute ...` и `Attribute ... is unknown`. Это может потребовать определения атрибутов в классе `PartyManager` или корректировки их использования в тестах.
    - Исправить ошибки `Type annotation not supported for this statement`.
    - Исправить ошибки `Cannot access attribute ... for class "FunctionType"`. Вероятно, это связано с неправильным использованием моков.
    - Исправить ошибки `Argument of type "str | None" cannot be assigned to parameter "key" of type "str"`.
6. **Обновить `agnets.md` и сделать коммит.**
7. **Исправить ошибки в файле `bot/command_modules/gm_app_cmds.py` (57 ошибок).**
    - Исправить ошибки импорта (`Import ... could not be resolved`, `... is unknown import symbol`).
    - Исправить ошибки `... is not awaitable`. Вероятно, это связано с отсутствием `await` там, где он нужен, или наоборот.
    - Исправить ошибки `Arguments missing for parameters ...`.
    - Исправить синтаксические ошибки (`Try statement must have at least one except or finally clause`, `Unexpected indentation`, `Expected expression`).
8. **Обновить `agnets.md` и сделать коммит.**
9. **Продолжать итеративно исправлять ошибки в остальных файлах, обрабатывая примерно по 1000 ошибок за раз (или по мере завершения работы с файлом).**
    - Для каждого файла или группы файлов:
        - Исправить ошибки.
        - Обновить `agnets.md` с указанием исправленных ошибок и текущего файла в работе.
        - Сделать коммит с описанием исправлений.
10. **После исправления всех ошибок, сделать финальный коммит и обновить `agnets.md`.**
