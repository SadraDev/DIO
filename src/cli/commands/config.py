from config.settings import settings

def run_config_management(
    show_all: bool = False,
    section: str = None,
    set_value: tuple = None,
    save_changes: bool = False,
    verbose: bool = False
):
    """View and modify configuration"""
    if show_all:
        print(settings.get_all())
    elif section:
        print(settings.get(section))
    elif set_value:
        key, value = set_value
        settings.set(key, value)
        if save_changes:
            settings.save_config()
