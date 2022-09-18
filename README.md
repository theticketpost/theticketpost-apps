# theticketpost-apps
Apps available to use with theticketpost-server

## Description file example
```json
{
    "name": "name_of_the_module",
    "description": "module_description",
    "version": "version",
    "author": "author_name",
    "render_component": true,
    "configuration": true,
    "inspector": true,
    "configuration_template": [
        {
            "type": "checkbox",
            "label": "Check Label",
            "name": "check_var",
            "value": true
        },
        {
            "type": "number",
            "label": "Number Label",
            "name": "number_var",
            "value": 0
        },
        {
            "type": "text",
            "label": "Text Label",
            "name": "text_var",
            "value": "default_value"
        }
    ],
    "inspector_template": [
        {
            "type": "file",
            "label": "File Label",
            "name": "file_var",
            "value": "default_value"
        }
    ]
}
```
