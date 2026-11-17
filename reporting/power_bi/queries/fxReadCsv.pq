// Create a blank query called fxReadCsv. This is a function; disable its load.
(FileName as text, ColumnTypes as list) as table =>
let
    Folder = Text.TrimEnd(DataFolder, {"\", "/"}),
    Source = Csv.Document(
        File.Contents(Folder & "/" & FileName),
        [Delimiter=",", Encoding=65001, QuoteStyle=QuoteStyle.Csv]
    ),
    Headers = Table.PromoteHeaders(Source, [PromoteAllScalars=true]),
    // Retain unavailable numeric values as null, never change them to zero.
    Nulls = Table.ReplaceValue(Headers, "", null, Replacer.ReplaceValue, Table.ColumnNames(Headers)),
    Typed = Table.TransformColumnTypes(Nulls, ColumnTypes, "en-US")
in
    Typed
