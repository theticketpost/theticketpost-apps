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
        },
        {
            "type": "select",
            "label": "Select Label",
            "name": "select_var",
            "value": "option_value_1",
            "options": [
                {
                    "value": "option_value_1",
                    "description": "option_description_1"
                },
                {
                    "value": "option_value_2",
                    "description": "option_description_2"
                }
            ]
        }
    ]
}
```

## Nothing to show today

When a component has nothing relevant to print (a calendar with no events, a feed with no news), put `data-ttp-empty` on an element of its HTML:

```html
<p data-ttp-empty>No upcoming events.</p>
```

The service leaves that section out of the printed ticket, and also any section tied to it in the editor ("Only if the section below/above is printed"), such as a title divider. The editor still shows it, dimmed. Don't mark errors this way: a section that failed should print, so the problem is seen.
