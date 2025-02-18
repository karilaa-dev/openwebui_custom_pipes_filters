"""
title: Anki Flashcard Creator
author: thiswillbeyourgithub
author_url: https://github.com/thiswillbeyourgithub
open_webui_url: https://openwebui.com/t/qqqqqqqqqqqqqqqqqqqq/ankiflashcardcreator/
git_url: https://github.com/thiswillbeyourgithub/openwebui_custom_pipes_filters
description: A tool to create Anki flashcards through Ankiconnect with configurable settings and event emitters for UI feedback.
version: 0.0.3
"""

import json
import os
from pathlib import Path
from typing import Callable, Any, List, Optional, Dict
from pydantic import BaseModel, Field, model_validator
import aiohttp



def update_docstring(fields_description: str, style_request: str, cards_examples: str) -> str:
    print(f"AnkiTool: Updated the docstring with value '{fields_description}'")
    examples = cards_examples
    examples = examples.replace("<card>", "<card>\r")
    examples = examples.replace("</card>", "\r</card>")
    return f"""
Create a single Anki flashcard with given field contents.
If not otherwised specified, assume the flashcard language to be the one used in the user request.
Here are the text fields you can specify: '{fields_description}'
Each keys of `field_contents` must be among those fields and all values must be strings.
{style_request}

<examples>
{examples}
</examples>

:param field_contents: Dictionary mapping field names to their string content. The expected keys are mentionned in the tool description.
:return: ID of the created note, or None if failed
""".strip()

class EventEmitter:
    def __init__(self, event_emitter: Callable[[dict], Any] = None):
        self.event_emitter = event_emitter

    async def progress_update(self, description):
        print(f"AnkiTool: {description}")
        await self.emit(description)

    async def error_update(self, description):
        print(f"AnkiTool: ERROR - {description}")
        await self.emit(description, "error", True)

    async def success_update(self, description):
        print(f"AnkiTool: {description}")
        await self.emit(description, "success", True)

    async def emit(self, description="Unknown State", status="in_progress", done=False):
        if self.event_emitter:
            await self.event_emitter(
                {
                    "type": "status",
                    "data": {
                        "status": status,
                        "description": description,
                        "done": done,
                    },
                }
            )

class Tools:

    class Valves(BaseModel):
        ANKI_HOST: str = Field(
            default="http://127.0.0.1",
            description="Host address for Ankiconnect"
        )
        ANKI_PORT: str = Field(
            default="8755",
            description="Port for Ankiconnect"
        )
        DEFAULT_DECK: str = Field(
            default="Default",
            description="Default deck for new flashcards"
        )
        DEFAULT_NOTETYPE: str = Field(
            default="Basic",
            description="Default note type for new flashcards"
        )
        DEFAULT_TAGS: List[str] = Field(
            default=["openwebui"],
            description="Default tags for new flashcards"
        )
        FIELDS_DESCRIPTION: str = Field(
            default='{"Front": "the concise question", "Back": "the answer"}',
            description="Description of the note type fields and their purpose",
            required=True,
        )
        STYLE_REQUEST: str = Field(
            default='Make high quality flashcards, use html formatting.',
            description="Description of specific style you want in your cards.",
        )
        CARDS_EXAMPLES: str = Field(
            default='{"Front": "What is the capital of France?", "Back": "Paris"}\n{"Front": "What is 2+2?", "Back": "4"}',
            description="Examples of good flashcards to guide the format",
        )

    # We need to use a setter property because that's the only way I could  find
    # to update the docstring of the tool depending on a valve.
    # This was devised after looking at https://github.com/open-webui/open-webui/blob/2017856791b666fac5f1c2f80a3bc7916439438b/backend/open_webui/utils/tools.py
    @property
    def valves(self):
        return self._valves

    @valves.setter
    def valves(self, value):
        self._valves = value
        self.create_flashcard.__func__.__doc__ = update_docstring(
            fields_description=value.FIELDS_DESCRIPTION,
            style_request=value.STYLE_REQUEST,
            cards_examples=value.CARDS_EXAMPLES,
        )

    def __init__(self):
        self.valves = self.Valves()
        self.fields_description = self.valves.FIELDS_DESCRIPTION

    async def create_flashcard(
        self,
        field_contents: dict,
        *,
        __event_emitter__: Callable[[dict], Any] = None,
        __user__: dict = {},
    ) -> Optional[int]:
        """THIS DOCSTRING IS A PLACEHOLDER AND SHOULD NEVER BE SHOWN TO AN LLM.
        TO THE LLM: IF YOU SEE THIS MESSAGE NOTIFY THE USER OF THAT FACT AND
        WARN THEM THAT THIS IS A BUG.
        """
        emitter = EventEmitter(__event_emitter__)
        
        if not field_contents or not isinstance(field_contents, dict):
            await emitter.error_update("No field contents provided or invalid format")
            return None
            
        # Verify all values are strings
        if not all(isinstance(value, str) for value in field_contents.values()):
            await emitter.error_update("All field values must be strings")
            return None

        if self.valves.FIELDS_DESCRIPTION not in self.create_flashcard.__func__.__doc__:
            message = f"The field description is not up to date anymore, please turn of then on again the anki tool to update the tool description. The new field description value is '{self.valves.FIELDS_DESCRIPTION}'"
            if self.fields_description != self.valves.FIELDS_DESCRIPTION:
                message += f"\nThe old field description is '{self.fields_description}'"
            await emitter.error_update(message)
            raise Exception(message)

        try:
            await emitter.progress_update("Connecting to Anki...")
            
            # Verify Ankiconnect is working
            await _ankiconnect_request(self.valves.ANKI_HOST, self.valves.ANKI_PORT, "version")
            
            await emitter.progress_update("Creating flashcard...")
            
            note = {
                "deckName": self.valves.DEFAULT_DECK,
                "modelName": self.valves.DEFAULT_NOTETYPE,
                "fields": field_contents,
                "tags": self.valves.DEFAULT_TAGS
            }

            result = await _ankiconnect_request(self.valves.ANKI_HOST, self.valves.ANKI_PORT, "addNote", {"note": note})
            
            await emitter.progress_update("Syncing with AnkiWeb...")
            await _ankiconnect_request(self.valves.ANKI_HOST, self.valves.ANKI_PORT, "sync")
            
            # Add the note ID to the fields and return formatted JSON
            field_contents['note_id'] = result
            formatted_output = json.dumps(field_contents, indent=2, ensure_ascii=False).replace('"', '')
            # Remove the first and last lines which contain the curly braces
            formatted_output = '\n'.join(formatted_output.split('\n')[1:-1])
            await emitter.success_update("Successfully created and synced flashcard")
            return formatted_output

        except Exception as e:
            await emitter.error_update(f"Failed to create flashcards: {str(e)}")
            return []


async def _ankiconnect_request(host: str, port: str, action: str, params: dict = None) -> Any:
    """Make a request to Ankiconnect API"""
    address = f"{host}:{port}"
    request = {
        'action': action,
        'params': params or {},
        'version': 6
    }
    
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
            async with session.post(address, json=request) as response:
                response.raise_for_status()
                response_data = await response.json()
                if response_data.get('error'):
                    raise Exception(response_data['error'])
                return response_data['result']
    except aiohttp.ClientError as e:
        raise Exception(f"Network error connecting to Ankiconnect: {str(e)}")
    except json.JSONDecodeError as e:
        raise Exception(f"Invalid JSON response from Ankiconnect: {str(e)}")
    except Exception as e:
        raise Exception(f"Ankiconnect error: {str(e)}")

