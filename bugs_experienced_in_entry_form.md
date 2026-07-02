
 Alright so the section switching requiring multiple clicks is still occurring. Every once in a while.
 We gotta add some debugging to see what's occurring.
 So that the logs can output what is occurring when the user clicks on an already closed section.

 So far, auto-scrolling while typing in the extra sections has been fixed.
 The table interaction dialog box that presents when the user selects a cell only appears on the bottom left in tables that are rather large. It functions normally when interacted with, however, it is impossible to use if the user is not at the bottom of the table for it to pop into view. Tables at an excess of 5 by 5 have this problem, however, we should be debugging such that it does not happen at all
 The table right click dialog box still does not perform any action when the user interacts with it.
 Table selection is no longer lost on right click.
 When trying to insert a table using the raw HTML modal, text is lost.
 After saving and leaving a session of reviewing in the entry form, and then returning to the session the assigned images are no longer found in the media attachments and The formatting of the table in additional notes is still not found. Conduct analysis of the database as how these are being saved may be the root cause. Viewing the entry in the entry browser shows that the image assigned to the entry is there, as well as the table in the question notes section displayed in raw html.
