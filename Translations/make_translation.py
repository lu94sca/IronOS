#!/usr/bin/env python3
# coding=utf-8
from __future__ import print_function
import argparse
import json
import os
import io
from datetime import datetime
import sys
import fontTables
import re
import subprocess
from bdflib import reader as bdfreader

HERE = os.path.dirname(__file__)

try:
    to_unicode = unicode
except NameError:
    to_unicode = str


with open(os.path.join(HERE, "wqy-bitmapsong/wenquanyi_9pt.bdf"), "rb") as handle:
    cjkFont = bdfreader.read_bdf(handle)


def log(message):
    print(message, file=sys.stdout)


# Loading a single JSON file
def loadJson(fileName, skipFirstLine):
    with io.open(fileName, mode="r", encoding="utf-8") as f:
        if skipFirstLine:
            f.readline()

        obj = json.loads(f.read())

    return obj


def readTranslation(jsonDir, langCode):
    fileName = 'translation_{}.json'.format(langCode)

    fileWithPath = os.path.join(jsonDir, fileName)

    try:
        lang = loadJson(fileWithPath, False)
    except json.decoder.JSONDecodeError as e:
        log("Failed to decode " + fileName)
        log(str(e))
        sys.exit(2)

    # Extract lang code from file name
    langCode = fileName[12:-5].upper()
    # ...and the one specified in the JSON file...
    try:
        langCodeFromJson = lang["languageCode"]
    except KeyError:
        langCodeFromJson = "(missing)"

    # ...cause they should be the same!
    if langCode != langCodeFromJson:
        raise ValueError(
            "Invalid languageCode " + langCodeFromJson + " in file " + fileName
        )

    return lang


def writeStart(f):
    f.write(
        to_unicode(
            """// WARNING: THIS FILE WAS AUTO GENERATED BY make_translation.py. PLEASE DO NOT EDIT.

#include "Translation.h"
"""
        )
    )


def escapeC(s):
    return s.replace('"', '\\"')


def getConstants():
    # Extra constants that are used in the firmware that are shared across all languages
    consants = []
    consants.append(("SymbolPlus", "+"))
    consants.append(("SymbolMinus", "-"))
    consants.append(("SymbolSpace", " "))
    consants.append(("SymbolDot", "."))
    consants.append(("SymbolDegC", "C"))
    consants.append(("SymbolDegF", "F"))
    consants.append(("SymbolMinutes", "M"))
    consants.append(("SymbolSeconds", "S"))
    consants.append(("SymbolWatts", "W"))
    consants.append(("SymbolVolts", "V"))
    consants.append(("SymbolDC", "DC"))
    consants.append(("SymbolCellCount", "S"))
    consants.append(("SymbolVersionNumber", buildVersion))
    return consants


def getDebugMenu():
    constants = []
    constants.append(datetime.today().strftime("%d-%m-%y"))
    constants.append("HW G ")  # High Water marker for GUI task
    constants.append("HW M ")  # High Water marker for MOV task
    constants.append("HW P ")  # High Water marker for PID task
    constants.append("Time ")  # Uptime (aka timestamp)
    constants.append("Move ")  # Time of last significant movement
    constants.append("RTip ")  # Tip reading in uV
    constants.append("CTip ")  # Tip temp in C
    constants.append("CHan ")  # Handle temp in C
    constants.append("Vin  ")  # Input voltage
    constants.append("PCB  ")  # PCB Version AKA IMU version
    constants.append("PWR  ")  # Power Negotiation State
    constants.append("Max  ")  # Max deg C limit

    return constants


def getLetterCounts(defs, lang):
    textList = []
    # iterate over all strings
    obj = lang["menuOptions"]
    for mod in defs["menuOptions"]:
        eid = mod["id"]
        textList.append(obj[eid]["desc"])

    obj = lang["messages"]
    for mod in defs["messages"]:
        eid = mod["id"]
        if eid not in obj:
            textList.append(mod["default"])
        else:
            textList.append(obj[eid])

    obj = lang["characters"]

    for mod in defs["characters"]:
        eid = mod["id"]
        textList.append(obj[eid])

    obj = lang["menuOptions"]
    for mod in defs["menuOptions"]:
        eid = mod["id"]
        textList.append(obj[eid]["text2"][0])
        textList.append(obj[eid]["text2"][1])

    obj = lang["menuGroups"]
    for mod in defs["menuGroups"]:
        eid = mod["id"]
        textList.append(obj[eid]["text2"][0])
        textList.append(obj[eid]["text2"][1])

    obj = lang["menuGroups"]
    for mod in defs["menuGroups"]:
        eid = mod["id"]
        textList.append(obj[eid]["desc"])
    constants = getConstants()
    for x in constants:
        textList.append(x[1])
    textList.extend(getDebugMenu())

    # collapse all strings down into the composite letters and store totals for these

    symbolCounts = {}
    for line in textList:
        line = line.replace("\n", "").replace("\r", "")
        line = line.replace("\\n", "").replace("\\r", "")
        if len(line):
            # print(line)
            for letter in line:
                symbolCounts[letter] = symbolCounts.get(letter, 0) + 1
    symbolCounts = sorted(
        symbolCounts.items(), key=lambda kv: (kv[1], kv[0])
    )  # swap to Big -> little sort order
    symbolCounts = list(map(lambda x: x[0], symbolCounts))
    symbolCounts.reverse()
    return symbolCounts

def getCJKGlyph(sym):
    from bdflib.model import Glyph
    try:
        glyph: Glyph = cjkFont[ord(sym)]
    except:
        return None
    data = glyph.data
    (srcLeft, srcBottom, srcW, srcH) = glyph.get_bounding_box()
    dstW = 12
    dstH = 16
    # The source data is a per-row list of ints. The first item is the bottom-
    # most row. For each row, the LSB is the right-most pixel.
    # Here, (x, y) is the coordinates with origin at the top-left.
    def getCell(x, y):
        # Adjust x coordinates by actual bounding box.
        adjX = x - srcLeft
        if adjX < 0 or adjX >= srcW:
            return False
        # Adjust y coordinates by actual bounding box, then place the glyph
        # baseline 3px above the bottom edge to make it centre-ish.
        # This metric is optimized for WenQuanYi Bitmap Song 9pt and assumes
        # each glyph is to be placed in a 12x12px box.
        adjY = y - (dstH - srcH - srcBottom - 3)
        if adjY < 0 or adjY >= srcH:
            return False
        if data[srcH - adjY - 1] & (1 << (srcW - adjX - 1)):
            return True
        else:
            return False
    # A glyph in the font table is divided into upper and lower parts, each by
    # 8px high. Each byte represents half if a column, with the LSB being the
    # top-most pixel. The data goes from the left-most to the right-most column
    # of the top half, then from the left-most to the right-most column of the
    # bottom half.
    s = ""
    for block in range(2):
        for c in range(dstW):
            b = 0
            for r in range(8):
                if getCell(c, r + 8 * block):
                    b |= 0x01 << r
            s += f"0x{b:02X},"
    return s

def getFontMapAndTable(textList):
    # the text list is sorted
    # allocate out these in their order as number codes
    symbolMap = {}
    symbolMap["\n"] = "\\x01"  # Force insert the newline char
    index = 2  # start at 2, as 0= null terminator,1 = new line
    forcedFirstSymbols = ["0", "1", "2", "3", "4", "5", "6", "7", "8", "9"]
    # enforce numbers are first
    for sym in forcedFirstSymbols:
        symbolMap[sym] = "\\x%0.2X" % index
        index = index + 1
    totalSymbolCount = len(set(textList) | set(forcedFirstSymbols))
    # \x00 is for NULL termination and \x01 is for newline, so the maximum
    # number of symbols allowed with 8 bits is `256 - 2`.
    if totalSymbolCount > (256 - 2):
        log(f"Error, too many used symbols for this version (total {totalSymbolCount})")
        exit(1)
    log("Generating fonts for {} symbols".format(totalSymbolCount))

    for sym in textList:
        if sym not in symbolMap:
            symbolMap[sym] = "\\x%0.2X" % index
            index = index + 1
    # Get the font table
    fontTableStrings = []
    fontSmallTableStrings = []
    fontTable = fontTables.getFontMap()
    fontSmallTable = fontTables.getSmallFontMap()
    for sym in forcedFirstSymbols:
        if sym not in fontTable:
            log("Missing Large font element for {}".format(sym))
            exit(1)
        fontLine = fontTable[sym]
        fontTableStrings.append(fontLine + "//{} -> {}".format(symbolMap[sym], sym))
        if sym not in fontSmallTable:
            log("Missing Small font element for {}".format(sym))
            exit(1)
        fontLine = fontSmallTable[sym]
        fontSmallTableStrings.append(
            fontLine + "//{} -> {}".format(symbolMap[sym], sym)
        )

    for sym in textList:
        if sym not in fontTable:
            # Assume this is a CJK character.
            fromFont = getCJKGlyph(sym)
            if fromFont is None:
                log("Missing Large font element for {}".format(sym))
                exit(1)
            # We store the glyph back to the fontTable.
            fontTable[sym] = fromFont
            # We also put a "replacement character" in the small font table
            # for sanity. (It is a question mark with inverted colour.)
            fontSmallTable[sym] = "0xFD, 0xFE, 0xAE, 0xF6, 0xF9, 0xFF,"
        if sym not in forcedFirstSymbols:
            fontLine = fontTable[sym]
            fontTableStrings.append(fontLine + "//{} -> {}".format(symbolMap[sym], sym))
            if sym not in fontSmallTable:
                log("Missing Small font element for {}".format(sym))
                exit(1)
            fontLine = fontSmallTable[sym]
            fontSmallTableStrings.append(
                fontLine + "//{} -> {}".format(symbolMap[sym], sym)
            )
    outputTable = "const uint8_t USER_FONT_12[] = {" + to_unicode("\n")
    for line in fontTableStrings:
        # join font table int one large string
        outputTable = outputTable + line + to_unicode("\n")
    outputTable = outputTable + "};" + to_unicode("\n")
    outputTable = outputTable + "const uint8_t USER_FONT_6x8[] = {" + to_unicode("\n")
    for line in fontSmallTableStrings:
        # join font table int one large string
        outputTable = outputTable + line + to_unicode("\n")
    outputTable = outputTable + "};" + to_unicode("\n")
    return (outputTable, symbolMap)


def convStr(symbolConversionTable, text):
    # convert all of the symbols from the string into escapes for their content
    outputString = ""
    for c in text.replace("\\r", "").replace("\\n", "\n"):
        if c not in symbolConversionTable:
            log("Missing font definition for {}".format(c))
        else:
            outputString = outputString + symbolConversionTable[c]
    return outputString


def writeLanguage(lang, defs, f):
    languageCode = lang['languageCode']
    log("Generating block for " + languageCode)
    # Iterate over all of the text to build up the symbols & counts
    textList = getLetterCounts(defs, lang)
    # From the letter counts, need to make a symbol translator & write out the font
    (fontTableText, symbolConversionTable) = getFontMapAndTable(textList)

    f.write(fontTableText)
    try:
        langName = lang["languageLocalName"]
    except KeyError:
        langName = languageCode

    f.write(to_unicode("// ---- " + langName + " ----\n\n"))

    # ----- Writing SettingsDescriptions
    obj = lang["menuOptions"]
    f.write(to_unicode("const char* SettingsDescriptions[] = {\n"))

    maxLen = 25
    index = 0
    for mod in defs["menuOptions"]:
        eid = mod["id"]
        if "feature" in mod:
            f.write(to_unicode("#ifdef " + mod["feature"] + "\n"))
        f.write(
            to_unicode(
                "  /* ["
                + "{:02d}".format(index)
                + "] "
                + eid.ljust(maxLen)[:maxLen]
                + " */ "
            )
        )
        f.write(
            to_unicode(
                '"'
                + convStr(symbolConversionTable, (obj[eid]["desc"]))
                + '",'
                + "//{} \n".format(obj[eid]["desc"])
            )
        )
        if "feature" in mod:
            f.write(to_unicode("#endif\n"))
        index = index + 1

    f.write(to_unicode("};\n\n"))

    # ----- Writing Message strings

    obj = lang["messages"]

    for mod in defs["messages"]:
        eid = mod["id"]
        sourceText = ""
        if "default" in mod:
            sourceText = mod["default"]
        if eid in obj:
            sourceText = obj[eid]
        translatedText = convStr(symbolConversionTable, sourceText)
        f.write(
            to_unicode(
                "const char* "
                + eid
                + ' = "'
                + translatedText
                + '";'
                + "//{} \n".format(sourceText.replace("\n", "_"))
            )
        )

    f.write(to_unicode("\n"))

    # ----- Writing Characters

    obj = lang["characters"]

    for mod in defs["characters"]:
        eid = mod["id"]
        f.write(
            to_unicode(
                "const char* "
                + eid
                + ' = "'
                + convStr(symbolConversionTable, obj[eid])
                + '";'
                + "//{} \n".format(obj[eid])
            )
        )

    f.write(to_unicode("\n"))

    # Write out firmware constant options
    constants = getConstants()
    for x in constants:
        f.write(
            to_unicode(
                "const char* "
                + x[0]
                + ' = "'
                + convStr(symbolConversionTable, x[1])
                + '";'
                + "//{} \n".format(x[1])
            )
        )

    f.write(to_unicode("\n"))

    # Debug Menu
    f.write(to_unicode("const char* DebugMenu[] = {\n"))

    for c in getDebugMenu():
        f.write(
            to_unicode(
                '\t "' + convStr(symbolConversionTable, c) + '",' + "//{} \n".format(c)
            )
        )
    f.write(to_unicode("};\n\n"))

    # ----- Writing SettingsDescriptions
    obj = lang["menuOptions"]
    f.write(to_unicode("const char* SettingsShortNames[][2] = {\n"))

    maxLen = 25
    index = 0
    for mod in defs["menuOptions"]:
        eid = mod["id"]
        if "feature" in mod:
            f.write(to_unicode("#ifdef " + mod["feature"] + "\n"))
        f.write(
            to_unicode(
                "  /* ["
                + "{:02d}".format(index)
                + "] "
                + eid.ljust(maxLen)[:maxLen]
                + " */ "
            )
        )
        f.write(
            to_unicode(
                '{ "'
                + convStr(symbolConversionTable, (obj[eid]["text2"][0]))
                + '", "'
                + convStr(symbolConversionTable, (obj[eid]["text2"][1]))
                + '" },'
                + "//{} \n".format(obj[eid]["text2"])
            )
        )

        if "feature" in mod:
            f.write(to_unicode("#endif\n"))
        index = index + 1

    f.write(to_unicode("};\n\n"))

    # ----- Writing Menu Groups
    obj = lang["menuGroups"]
    f.write(to_unicode("const char* SettingsMenuEntries[" + str(len(obj)) + "] = {\n"))

    maxLen = 25
    for mod in defs["menuGroups"]:
        eid = mod["id"]
        f.write(to_unicode("  /* " + eid.ljust(maxLen)[:maxLen] + " */ "))
        f.write(
            to_unicode(
                '"'
                + convStr(
                    symbolConversionTable,
                    (obj[eid]["text2"][0]) + "\\n" + obj[eid]["text2"][1],
                )
                + '",'
                + "//{} \n".format(obj[eid]["text2"])
            )
        )

    f.write(to_unicode("};\n\n"))

    # ----- Writing Menu Groups Descriptions
    obj = lang["menuGroups"]
    f.write(
        to_unicode(
            "const char* SettingsMenuEntriesDescriptions[" + str(len(obj)) + "] = {\n"
        )
    )

    maxLen = 25
    for mod in defs["menuGroups"]:
        eid = mod["id"]
        f.write(to_unicode("  /* " + eid.ljust(maxLen)[:maxLen] + " */ "))
        f.write(
            to_unicode(
                '"'
                + convStr(symbolConversionTable, (obj[eid]["desc"]))
                + '",'
                + "//{} \n".format(obj[eid]["desc"])
            )
        )

    f.write(to_unicode("};\n\n"))
    f.write("const bool HasFahrenheit = " + (
        "true" if lang.get('tempUnitFahrenheit', True) else "false") +
        ";\n")



def readVersion(jsonDir):
    with open(os.path.relpath(jsonDir + "/../source/version.h"), "r") as version_file:
        try:
            for line in version_file:
                if re.findall(r"^.*(?<=(#define)).*(?<=(BUILD_VERSION))", line):
                    line = re.findall(r"\"(.+?)\"", line)
                    if line:
                        version = line[0]
                        try:
                            version += (
                                "."
                                + subprocess.check_output(
                                    ["git", "rev-parse", "--short=7", "HEAD"]
                                )
                                .strip()
                                .decode("ascii")
                                .upper()
                            )
                        # --short=7: the shorted hash with 7 digits. Increase/decrease if needed!
                        except OSError:
                            version += " git"
        finally:
            if version_file:
                version_file.close()
                return version


def orderOutput(langDict):
    # These languages go first
    mandatoryOrder = ["EN"]

    # Then add all others in alphabetical order
    sortedKeys = sorted(langDict.keys())

    # Add the rest as they come
    for key in sortedKeys:
        if key not in mandatoryOrder:
            mandatoryOrder.append(key)

    return mandatoryOrder


def parseArgs():
    parser = argparse.ArgumentParser()
    parser.add_argument(
            '--output', '-o',
            help='Target file', type=argparse.FileType('w'), required=True)
    parser.add_argument('languageCode', help='Language to generate')
    return parser.parse_args()


if __name__ == "__main__":
    jsonDir = HERE

    args = parseArgs()

    try:
        buildVersion = readVersion(jsonDir)
    except:
        log("error: could not get/extract build version")
        sys.exit(1)

    log("Build version: " + buildVersion)
    log("Making " + args.languageCode + " from " + jsonDir)

    lang = readTranslation(jsonDir, args.languageCode)
    defs = loadJson(os.path.join(jsonDir, "translations_def.js"), True)
    out = args.output
    writeStart(out)
    writeLanguage(lang, defs, out)

    log("Done")
