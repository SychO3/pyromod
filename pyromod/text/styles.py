from typing import Type, Union

from abc import ABC

from .bases import Element, PlainText, Text


class Style(Element, ABC):
    """Class that inherits each style. it isolates a part of logic how to
    render styles.

    Args:
        text (Union[str, text.bases.Element]):
            Text or Element to which the style will be applied.
    """

    markdown_symbol: str
    html_tag: str
    html_class: Union[str, None] = None
    base_style_fabric: Union[Type[Text], Type['Style']] = PlainText

    def __init__(self, text: Union[str, Element]):
        if isinstance(text, str):
            text = self.base_style_fabric(text)
        if isinstance(text, Style) and self.__class__ is text.__class__:
            text = text.text
        self.text: Element = text

    def to_plain_text(self) -> str:
        return self.text.to_plain_text()

    def to_markdown(self) -> str:
        return f"{self.markdown_symbol}{self.text.to_markdown()}{self.markdown_symbol}"

    def to_html(self) -> str:
        class_str = f' class="{self.html_class}"' if self.html_class else ''
        return f'<{self.html_tag}{class_str}>{self.text.to_html()}</{self.html_tag}>'

    def __repr__(self) -> str:
        text = f"'{self.text}'" if isinstance(self.text, self.base_style_fabric) else repr(self.text)
        return f"<{self.__class__.__name__}: {text}>"


class Bold(Style):
    """Bold text. Example: **bold text**."""

    markdown_symbol = '**'
    html_tag = 'b'


class Strong(Bold):
    """Bold text rendered with the ``strong`` HTML tag."""

    html_tag = 'strong'


class Italic(Style):
    """Italic text. Example: __italic text__."""

    markdown_symbol = '__'
    html_tag = 'i'


class Em(Italic):
    """Italic text rendered with the ``em`` HTML tag."""

    html_tag = 'em'


class Underline(Style):
    """Underline text. Example: --underline text--."""

    markdown_symbol = '--'
    html_tag = 'u'


class Ins(Underline):
    """Underline text rendered with the ``ins`` HTML tag."""

    html_tag = 'ins'


class Strikethrough(Style):
    """Strikethrough text. Example: ~~strikethrough text~~."""

    markdown_symbol = '~~'
    html_tag = 's'


class Del(Strikethrough):
    """Strikethrough text rendered with the ``del`` HTML tag."""

    html_tag = 'del'


class Strike(Strikethrough):
    """Strikethrough text rendered with the ``strike`` HTML tag."""

    html_tag = 'strike'


class Spoiler(Style):
    """Spoiler text. We can't provide an example because it's a very specific
    for Telegram messenger formatting.
    """

    markdown_symbol = '||'
    html_tag = 'tg-spoiler'
    html_class = None


class InlineCode(Style):
    """Inline code text. Example: :code:`inline code`."""

    markdown_symbol = '`'
    html_tag = 'code'
    base_style_fabric = Text


class Code(Style):
    """Code block for many lines of text. Telegram doesn't support frontend
    language-specific highlights, but according to documentation, it provides
    an opportunity to specify a language. Perhaps, the Telegram team will add
    support for this in the future.

    Args:
        text (str):
            Text of code block.
        language (Optional[str]):
            Leave it empty if you don't want to specify a language.
    """

    markdown_symbol = '```'
    html_tag = 'code'
    base_style_fabric = Text

    def __init__(self, text: str, language: Union[str, None] = None):
        super().__init__(text)
        self.language: str = language or ''
        self.html_class: Union[str, None] = f'language-{language}' if language else None

    def to_markdown(self) -> str:
        return f"{self.markdown_symbol}{self.language}\n{self.text.to_markdown()}\n{self.markdown_symbol}"

    def to_html(self) -> str:
        # if lang isn't specified, we don't use <code> tag according to Telegram docs
        if self.html_class:
            return f'<pre>{super().to_html()}</pre>'
        return f'<pre>{self.text.to_html()}</pre>'


class Quote(Style):
    """Quote block.
    See an example below.

        Block quotation started

        Block quotation continued

        The last line of the block quotation
    """

    markdown_symbol = '>'
    html_tag = 'blockquote'

    def to_markdown(self) -> str:
        return '\n'.join(
            f"{self.markdown_symbol} {line}" if line else self.markdown_symbol
            for line in self.text.to_markdown().split('\n')
        )


class ExpandableQuote(Quote):
    """Quote block that renders as ``<blockquote expandable>`` in HTML."""

    def to_html(self) -> str:
        return f'<blockquote expandable>{self.text.to_html()}</blockquote>'
