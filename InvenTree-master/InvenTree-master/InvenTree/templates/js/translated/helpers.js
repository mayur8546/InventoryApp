{% load i18n %}

/* exported
    blankImage,
    deleteButton,
    editButton,
    formatDecimal,
    imageHoverIcon,
    makeIconBadge,
    makeIconButton,
    makeProgressBar,
    renderLink,
    sanitizeInputString,
    select2Thumbnail,
    setupNotesField,
    shortenString,
    thumbnailImage
    yesNoLabel,
    withTitle,
*/

function yesNoLabel(value) {
    if (value) {
        return `<span class='badge rounded-pill bg-success'>{% trans "YES" %}</span>`;
    } else {
        return `<span class='badge rounded-pill bg-warning'>{% trans "NO" %}</span>`;
    }
}


function editButton(url, text='{% trans "Edit" %}') {
    return `<button class='btn btn-success edit-button btn-sm' type='button' url='${url}'>${text}</button>`;
}


function deleteButton(url, text='{% trans "Delete" %}') {
    return `<button class='btn btn-danger delete-button btn-sm' type='button' url='${url}'>${text}</button>`;
}



/*
 * Ensure a string does not exceed a maximum length.
 * Useful for displaying long strings in tables,
 * to ensure a very long string does not "overflow" the table
 */
function shortenString(input_string, options={}) {

    // Maximum length can be provided via options argument, or via a user-configurable setting
    var max_length = options.max_length || user_settings.TABLE_STRING_MAX_LENGTH;

    if (!max_length || !input_string) {
        return input_string;
    }

    input_string = input_string.toString();

    // Easy option: input string is already short enough
    if (input_string.length <= max_length) {
        return input_string;
    }

    var N = Math.floor(max_length / 2 - 1);

    var output_string = input_string.slice(0, N) + '...' + input_string.slice(-N);

    return output_string;
}


function withTitle(html, title, options={}) {

    return `<div title='${title}'>${html}</div>`;
}


/* Format a decimal (floating point) number, to strip trailing zeros
 */
function formatDecimal(number, places=5) {
    return +parseFloat(number).toFixed(places);
}


function blankImage() {
    return `/static/img/blank_image.png`;
}

/* Render a small thumbnail icon for an image.
 * On mouseover, display a full-size version of the image
 */
function imageHoverIcon(url) {

    if (!url) {
        url = blankImage();
    }

    var html = `
        <a class='hover-icon'>
            <img class='hover-img-thumb' src='${url}'>
            <img class='hover-img-large' src='${url}'>
        </a>
        `;

    return html;
}


/**
 * Renders a simple thumbnail image
 * @param {String} url is the image URL
 * @returns html <img> tag
 */
function thumbnailImage(url, options={}) {

    if (!url) {
        url = blankImage();
    }

    // TODO: Support insertion of custom classes
    var title = options.title || '';

    var html = `<img class='hover-img-thumb' src='${url}' title='${title}'>`;

    return html;

}


// Render a select2 thumbnail image
function select2Thumbnail(image) {
    if (!image) {
        image = blankImage();
    }

    return `<img src='${image}' class='select2-thumbnail'>`;
}


/*
 * Construct an 'icon badge' which floats to the right of an object
 */
function makeIconBadge(icon, title) {

    var html = `<span class='icon-badge fas ${icon} float-right' title='${title}'></span>`;

    return html;
}


/*
 * Construct an 'icon button' using the fontawesome set
 */
function makeIconButton(icon, cls, pk, title, options={}) {

    var classes = `btn btn-outline-secondary ${cls}`;

    var id = `${cls}-${pk}`;

    var html = '';

    var extraProps = '';

    if (options.disabled) {
        extraProps += `disabled='true' `;
    }

    if (options.collapseTarget) {
        extraProps += `data-bs-toggle='collapse' href='#${options.collapseTarget}'`;
    }

    html += `<button pk='${pk}' id='${id}' class='${classes}' title='${title}' ${extraProps}>`;
    html += `<span class='fas ${icon}'></span>`;
    html += `</button>`;

    return html;
}


/*
 * Render a progessbar!
 *
 * @param value is the current value of the progress bar
 * @param maximum is the maximum value of the progress bar
 */
function makeProgressBar(value, maximum, opts={}) {

    var options = opts || {};

    value = formatDecimal(parseFloat(value));

    var percent = 100;

    // Prevent div-by-zero or null value
    if (maximum && maximum > 0) {
        maximum = formatDecimal(parseFloat(maximum));
        percent = formatDecimal(parseInt(value / maximum * 100));
    }

    if (percent > 100) {
        percent = 100;
    }

    var extraclass = '';

    if (value > maximum) {
        extraclass='progress-bar-over';
    } else if (value < maximum) {
        extraclass = 'progress-bar-under';
    }

    var style = options.style || '';

    var text = options.text;

    if (!text) {
        if (style == 'percent') {
            // Display e.g. "50%"

            text = `${percent}%`;
        } else if (style == 'max') {
            // Display just the maximum value
            text = `${maximum}`;
        } else if (style == 'value') {
            // Display just the current value
            text = `${value}`;
        } else if (style == 'blank') {
            // No display!
            text = '';
        } else {
            /* Default style
            * Display e.g. "5 / 10"
            */

            text = `${value} / ${maximum}`;
        }
    }

    var id = options.id || 'progress-bar';

    var style = '';

    if (opts.max_width) {
        style += `max-width: ${options.max_width}; `;
    }

    return `
    <div id='${id}' class='progress' style='${style}'>
        <div class='progress-bar ${extraclass}' role='progressbar' aria-valuenow='${percent}' aria-valuemin='0' aria-valuemax='100' style='width:${percent}%'></div>
        <div class='progress-value'>${text}</div>
    </div>
    `;
}


/*
 * Render a URL for display
 */
function renderLink(text, url, options={}) {
    if (url === null || url === undefined || url === '') {
        return text;
    }

    var max_length = options.max_length || 0;

    if (max_length > 0) {
        text = shortenString(text, {
            max_length: max_length,
        });
    }

    var extras = '';

    if (options.tooltip != false) {
        extras += ` title="${url}"`;
    }

    if (options.download) {
        extras += ` download`;
    }

    return `<a href="${url}" ${extras}>${text}</a>`;
}


function setupNotesField(element, url, options={}) {

    var editable = options.editable || false;

    // Read initial notes value from the URL
    var initial = null;

    inventreeGet(url, {}, {
        async: false,
        success: function(response) {
            initial = response[options.notes_field || 'notes'];
        },
    });

    var toolbar_icons = [
        'preview', '|',
    ];

    if (editable) {
        // Heading icons
        toolbar_icons.push('heading-1', 'heading-2', 'heading-3', '|');

        // Font style
        toolbar_icons.push('bold', 'italic', 'strikethrough', '|');

        // Text formatting
        toolbar_icons.push('unordered-list', 'ordered-list', 'code', 'quote', '|');

        // Elements
        toolbar_icons.push('table', 'link', 'image');
    }

    // Markdown syntax guide
    toolbar_icons.push('|', 'guide');

    const mde = new EasyMDE({
        element: document.getElementById(element),
        initialValue: initial,
        toolbar: toolbar_icons,
        shortcuts: [],
        renderingConfig: {
            markedOptions: {
                sanitize: true,
            }
        }
    });


    // Hide the toolbar
    $(`#${element}`).next('.EasyMDEContainer').find('.editor-toolbar').hide();

    if (!editable) {
        // Set readonly
        mde.codemirror.setOption('readOnly', true);

        // Hide the "edit" and "save" buttons
        $('#edit-notes').hide();
        $('#save-notes').hide();

    } else {
        mde.togglePreview();

        // Add callback for "edit" button
        $('#edit-notes').click(function() {
            $('#edit-notes').hide();
            $('#save-notes').show();

            // Show the toolbar
            $(`#${element}`).next('.EasyMDEContainer').find('.editor-toolbar').show();

            mde.togglePreview();
        });

        // Add callback for "save" button
        $('#save-notes').click(function() {

            var data = {};

            data[options.notes_field || 'notes'] = mde.value();

            inventreePut(url, data, {
                method: 'PATCH',
                success: function(response) {
                    showMessage('{% trans "Notes updated" %}', {style: 'success'});
                },
                error: function(xhr) {
                    showApiError(xhr, url);
                }
            });
        });
    }
}


/*
 * Sanitize a string provided by the user from an input field,
 * e.g. data form or search box
 *
 * - Remove leading / trailing whitespace
 * - Remove hidden control characters
 */
function sanitizeInputString(s, options={}) {

    if (!s) {
        return s;
    }

    // Remove ASCII control characters
    s = s.replace(/[\x00-\x1F\x7F]+/g, '');

    // Remove Unicode control characters
    s = s.replace(/[\p{C}]+/gu, '');

    s = s.trim();

    return s;
}
