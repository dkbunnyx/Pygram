# Pygram — Changelog

История изменений Pygram Beta 0.1–0.2.6.

## Содержание

- [Beta 0.1](#beta-01)
- [Beta 0.2](#beta-02)
- [Beta 0.2.1](#beta-021)
- [Beta 0.2.2](#beta-022)
- [Beta 0.2.3](#beta-023)
- [Beta 0.2.4](#beta-024)
- [Beta 0.2.5](#beta-025)
- [Beta 0.2.6](#beta-026)

---

<a id="beta-01"></a>
# Pygram Beta 0.1

<img src="./assets/changelog/features.svg" alt="Features" height="22" />

- `fix(identity)`: при регистрации логин стал сохраняться в открытом виде в маркере `.logins/`. Это исправило отображение обрезанного хеша вместо логина в личных чатах.
- `feat(chat_list)`: добавлена автоматическая синхронизация логинов из общей папки в SQLite при запуске приложения. Старые аккаунты теперь корректно отображаются на новых компьютерах.
- `feat(status)`: добавлено физическое удаление всех сообщений чата через `physically_delete_all_messages`.
- `feat(chat_view)`: действие «Удалить историю (у обоих)» теперь физически удаляет `.bin`-файлы сообщений из общей папки.
- `fix(sync)`: `sync_messages_to_db` удаляет записи из локальной БД, если соответствующие файлы сообщений были удалены из общей папки.

<img src="./assets/changelog/bug-fixes.svg" alt="Bug Fixes" height="22" />

- `fix(status)`: удалено повторное создание директории после `rmtree`, чтобы устранить ошибку `WinError 183` при работе с SMB.

<img src="./assets/changelog/build.svg" alt="Build & Release" height="22" />

- `build`: обновлён `Pygram.spec`.
- `build`: пересобран исполняемый файл `Pygram.exe` Beta 0.1.

---

<a id="beta-02"></a>
# Pygram Beta 0.2

<img src="./assets/changelog/bug-fixes.svg" alt="Bug Fixes" height="22" />

- `fix(ui)`: исправлена работа контекстного меню удаления сообщений по правому клику. Ранее меню могло не срабатывать или удалять не то сообщение.

---

<a id="beta-021"></a>
# Pygram Beta 0.2.1

<img src="./assets/changelog/features.svg" alt="Features" height="22" />

- `feat(chat_list)`: добавлен фоновый `SyncAllWorker`, запускаемый таймером `MainWindow` каждые 3 секунды. Теперь синхронизируются все чаты, а не только открытый.
- `feat(emoji_picker)`: список эмодзи расширен примерно до 600+ символов. Добавлены категории животных и природы, еды, транспорта, активностей, объектов и символов.

<img src="./assets/changelog/bug-fixes.svg" alt="Bug Fixes" height="22" />

- `fix(notifications)`: исправлено отсутствие уведомлений для чатов, которые не были открыты. Ранее `sync_messages_to_db` запускался только для активного чата, из-за чего счётчик непрочитанного оставался равен нулю.
- `fix(main_window)`: метод `_tick`, ошибочно вложенный в `__init__`, перенесён на уровень класса.
- `fix(chat_list)`: `set_user` теперь сбрасывает `_last_unread` и `current_open_chat_id`.
- `fix(sync)`: для синхронизации списка чатов используется `prune_missing=False`, чтобы несколько одновременно работающих клиентов не удаляли записи друг друга из общей SQLite. В `chat_view` сохранён `prune_missing=True`.
- `fix(local_db)`: добавлен `PRAGMA busy_timeout=5000` и повтор операции при `OperationalError: database is locked`.
- `fix(message)`: удалена дублирующая старая реализация `sync_messages_to_db`, которая переопределяла новую версию с `prune_missing`.
- `fix(settings_view)`: заголовок «Цвета интерфейса» и разделитель скрываются вместе с блоком цветов при выборе базовой темы.
- `fix(settings_view)`: при переключении на базовую тему локальные цвета SQLite сбрасываются к значениям по умолчанию.
- `fix(chat_view)`: `load_chat` принудительно загружает стандартные цвета делегата для базовой темы.
- `fix(main_window)`: при переключении на базовую тему делегат принудительно перерисовывается через `dataChanged.emit()`.

<img src="./assets/changelog/build.svg" alt="Build & Release" height="22" />

- `fix(build)`: из `Pygram.spec` удалён несуществующий модуль `plyer.platforms.win.libs.win_gui`.
- `build`: пересобран `Pygram.exe`, чтобы в заголовке уведомлений Windows отображалось имя Pygram, а не Python.

---

<a id="beta-022"></a>
# Pygram Beta 0.2.2

<img src="./assets/changelog/architecture.svg" alt="Architecture & Refactoring" height="22" />

- `refactor(config)`: удалена неиспользуемая константа `DEFAULT_SHARED_FOLDER = r"\\Server\Share\Pygram"`.
- `refactor(config)`: `ensure_config()` теперь требует явный параметр `shared_folder: str`.

<img src="./assets/changelog/bug-fixes.svg" alt="Bug Fixes" height="22" />

- `fix(main)`: удалены повторные импорты `sys` и `Path`.
- `fix(main)`: при ошибке создания общей папки `QMessageBox` теперь показывает текст исключения.
- `fix(main)`: при автоматическом создании общей папки записывается предупреждение в лог.

<img src="./assets/changelog/build.svg" alt="Build & Release" height="22" />

- `build`: пересобран `Pygram.exe` Beta 0.2.2 с параметром `--clean`.

---

<a id="beta-023"></a>
# Pygram Beta 0.2.3

<img src="./assets/changelog/documentation.svg" alt="Documentation & GitHub" height="22" />

- `docs`: заполнены `docs/changelog.md` и `docs/architecture.md`.
- `docs`: удалён устаревший `docs/api.md`.

<img src="./assets/changelog/architecture.svg" alt="Architecture & Refactoring" height="22" />

- `chore`: удалены пустые заглушки `scripts/backup.py`, `build.py`, `init_db.py`, `migrate.py`, `restore.py` и пустой `tests/test_storage.py`.
- `chore`: обновлён `.gitignore` для служебных файлов, логов и каталогов сборки. `Pygram.spec` больше не игнорируется.

---

<a id="beta-024"></a>
# Pygram Beta 0.2.4

<img src="./assets/changelog/major-update.svg" alt="Major Update" height="22" />

**Зашифрованные вложения и встроенный просмотр изображений.**

<img src="./assets/changelog/features.svg" alt="Features" height="22" />

- `feat(attachments)`: добавлена отправка и получение зашифрованных вложений.
- `feat(message)`: метаданные вложений связываются с сообщением, а зашифрованные файлы хранятся в общей папке.
- `feat(ui)`: расшифрованные изображения отображаются непосредственно во встроенном просмотрщике Pygram.
- `feat(ui)`: левый клик по фотографии или скриншоту открывает встроенный просмотрщик вместо стандартного приложения Windows.

<img src="./assets/changelog/security.svg" alt="Security" height="22" />

- `feat(crypto)`: реализовано потоковое шифрование вложений AES-256-GCM.
- `feat(crypto)`: для каждого вложения генерируется отдельный случайный AES-ключ.
- `feat(crypto)`: для личных чатов AES-ключ оборачивается RSA-OAEP отдельно для каждого получателя; в групповых чатах используется ключ группы.
- `feat(security)`: добавлена проверка целостности GCM и привязка AAD к чату, имени файла и отправителю.

<img src="./assets/changelog/performance.svg" alt="Performance & Sync" height="22" />

- `feat(ui)`: расшифровка изображений для предпросмотра выполняется в фоновом режиме, не блокируя графический интерфейс.

---

<a id="beta-025"></a>
# Pygram Beta 0.2.5

<img src="./assets/changelog/major-update.svg" alt="Major Update" height="22" />

**Крупное обновление безопасности: Root Trust, Login Guard и защищённые права доступа.**

<img src="./assets/changelog/security.svg" alt="Security" height="22" />

- `feat(trust)`: добавлено локальное закрепление (pinning) отпечатка первого супер-администратора и цепочки доверия Root Trust.
- `feat(admin)`: формат `.admins/list.json` переработан: добавлены самоподписанный корень, проверка цепочки подписей, ограничения размера файла и количества записей.
- `feat(login_guard)`: добавлены локальные ограничения частоты попыток входа с интервалами блокировки 30, 60 и 180 секунд.
- `feat(identity)`: добавлен `InvalidPasswordError`.
- `feat(shared_store)`: при сохранении и загрузке публичного ключа выполняется проверка соответствия отпечатка и ключа.
- `refactor(shared_store)`: реализована атомарная запись через `write_bytes_atomic` с заменой файла и повторными попытками вместо небезопасной прямой записи.
- `feat(crypto)`: при потоковом шифровании и расшифровании временные файлы синхронизируются через `fsync`.
- `feat(admin)`: добавлены `can_grant_delete_rights` и `toggle_delete_others_rights`.

<img src="./assets/changelog/features.svg" alt="Features" height="22" />

- `feat(ui)`: добавлено удаление чужих сообщений с учётом назначенных прав.
- `feat(ui)`: при входе с нового компьютера добавлено подтверждение отпечатка супер-администратора.
- `feat(ui)`: добавлена кнопка удержания для показа введённого пароля.
- `feat(ui)`: фоновое удаление перенесено в `DeleteWorker`, добавлена обработка ошибок.

<img src="./assets/changelog/bug-fixes.svg" alt="Bug Fixes" height="22" />

- `fix(ui)`: исправлена ошибка кодировки строк в `profile_view`.

<img src="./assets/changelog/build.svg" alt="Build & Release" height="22" />

- `build`: добавлен `Pygram.spec` для PyInstaller.

<img src="./assets/changelog/tests.svg" alt="Tests" height="22" />

- `test`: добавлены тесты Root Trust, Login Guard, прав удаления и атомарной записи.

---

<a id="beta-026"></a>
# Pygram Beta 0.2.6

<img src="./assets/changelog/major-update.svg" alt="Major Update" height="22" />

**Два крупных направления обновления: восстановление супер-администратора и Event Engine.**

## Superadmin Recovery

<img src="./assets/changelog/features.svg" alt="Features" height="22" />

- `feat(recovery)`: добавлена отдельная настройка пароля восстановления при первом создании супер-администратора, а также при первом входе существующего супер-администратора после обновления.
- `feat(recovery)`: реализовано создание новой учётной записи супер-администратора с переносом проверенного списка администраторов.
- `feat(recovery)`: прежняя учётная запись корневого администратора становится обычным администратором с эквивалентными правами; существующие права остальных администраторов сохраняются.

<img src="./assets/changelog/security.svg" alt="Security" height="22" />

- `feat(recovery)`: добавлено локальное закрепление публичного ключа восстановления, подписанный root descriptor и сертификат перехода к новому корню.
- `feat(trust)`: клиенты, заранее закрепившие публичный ключ восстановления, могут безопасно обновить локальный root pin после проверки сертификата.
- `feat(admin)`: версия подписи v2 включает `can_grant_delete_rights`; подписи старого формата v1 продолжают проверяться для обратной совместимости.
- `safety`: восстановление не изменяет пользовательские аккаунты, личные и групповые чаты, сообщения, вложения, медиафайлы и ключи чатов.

<img src="./assets/changelog/tests.svg" alt="Tests" height="22" />

- `test`: добавлены проверки переноса администраторов, сохранности файлов чатов и медиа, регистрации ключа восстановления и миграции доверия на втором компьютере.

> **Важно:** после настройки восстановления клиенты должны хотя бы один раз подключиться к действующему супер-администратору, чтобы локально закрепить публичный ключ восстановления. Только после этого они смогут проверить переход на нового корневого администратора.

## Event Engine

<img src="./assets/changelog/major-update.svg" alt="Major Update" height="22" />

**Централизованная событийная архитектура и синхронизация приложения.**

<img src="./assets/changelog/architecture.svg" alt="Architecture & Refactoring" height="22" />

- `feat(event_engine)`: внедрена центральная событийная архитектура.
- `feat(qt_signal_bridge)`: добавлен `QtSignalBridge` для безопасной передачи событий из фоновых потоков в GUI-поток Qt.
- `feat(tick_engine)`: создан централизованный планировщик фоновых задач, заменивший разрозненные периодические таймеры.
- `feat(sync_engine)`: реализован централизованный `SyncEngine` с параллельной обработкой, ограничением числа workers и объединением повторных запросов.
- `feat(file_transport)`: реализовано наблюдение за несколькими директориями через один Watchdog Observer.
- `feat(file_transport)`: добавлена публикация событий создания, изменения, удаления и перемещения файлов.

<img src="./assets/changelog/features.svg" alt="Features" height="22" />

- `feat(chat_view)`: обновление сообщений, реакций, статусов прочтения, присутствия пользователей и изменений групп переведено на событийную модель.
- `feat(chat_list)`: синхронизация списка чатов переведена на центральный `SyncEngine`.
- `feat(group_settings)`: настройки и список участников группы автоматически обновляются при изменении метаданных группы.

<img src="./assets/changelog/bug-fixes.svg" alt="Bug Fixes" height="22" />

- `fix(trust)`: улучшена обработка Root Trust и доверенных корневых администраторов.
- `fix(admin/user)`: внесены исправления в управление администраторами и пользователями.
- `fix(local_db)`: внесены изменения в локальную базу данных SQLite.
- `fix(main)`: устранено повторное создание `QApplication`.

<img src="./assets/changelog/tests.svg" alt="Tests" height="22" />

- `test(event_engine)`: добавлены тесты событийной архитектуры, маршрутизации событий чатов, `QtSignalBridge`, `TickEngine` и `SyncEngine`.
- `test(file_transport)`: добавлены тесты мониторинга нескольких директорий.
- `test(superadmin_recovery)`: добавлены тесты восстановления супер-администратора.

<img src="./assets/changelog/documentation.svg" alt="Documentation & GitHub" height="22" />

- `docs`: обновлена документация архитектуры.
- `docs`: добавлена документация Event Engine.
- `docs`: обновлён changelog.
- `docs`: обновлён changelog: добавлено цветное оформление категорий с помощью SVG-меток на прозрачном фоне, а также улучшена навигация по версиям.

---

*Pygram — changelog Beta 0.1–0.2.6.*
