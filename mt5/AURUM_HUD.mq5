//+------------------------------------------------------------------+
//|                                                    AURUM_HUD.mq5  |
//|         AURUM AI — STEP 1: MARKET STRUCTURE MAPPING               |
//|                                                                   |
//|  Renders the structure the Python agent maps. The agent writes    |
//|  aurum_structure.csv into the MT5 *common* Files folder; this     |
//|  indicator reads it and draws ONLY the objects tagged for this    |
//|  chart's timeframe (MS_<TF>_...). Attach one instance per chart   |
//|  timeframe you want to see (e.g. an M15 chart and an H1 chart).   |
//|                                                                   |
//|  INSTALL:                                                         |
//|   1. MT5 menu: File -> Open Data Folder -> MQL5 -> Indicators      |
//|      copy AURUM_HUD.mq5 there.                                    |
//|   2. MetaEditor: open it, press F7 to compile (0 errors).         |
//|   3. MT5: open an XAUUSD chart, drag AURUM_HUD onto it.           |
//|      No DLLs, no algo-trading permission needed (read-only).      |
//+------------------------------------------------------------------+
#property copyright "AURUM AI"
#property version   "2.00"
#property indicator_chart_window
#property indicator_plots 0

input int    RefreshSeconds = 3;                       // file poll interval
input string OverlayFile    = "aurum_structure.csv";   // in COMMON\Files
input int    SweepBoxBars   = 14;                      // sweep box width (bars)

const string PFX = "MS_";

//+------------------------------------------------------------------+
int OnInit()
  {
   EventSetTimer(MathMax(1, RefreshSeconds));
   Render();
   return(INIT_SUCCEEDED);
  }
void OnDeinit(const int reason) { EventKillTimer(); ClearAll(); ChartRedraw(); }
void OnTimer() { Render(); }

int OnCalculate(const int rates_total, const int prev_calculated,
                const datetime &time[], const double &open[],
                const double &high[], const double &low[],
                const double &close[], const long &tick_volume[],
                const long &volume[], const int &spread[])
  { return(rates_total); }

//+------------------------------------------------------------------+
//| This chart's timeframe as the string the agent uses              |
//+------------------------------------------------------------------+
string TFString()
  {
   switch(Period())
     {
      case PERIOD_M1:  return("M1");
      case PERIOD_M5:  return("M5");
      case PERIOD_M15: return("M15");
      case PERIOD_M30: return("M30");
      case PERIOD_H1:  return("H1");
      case PERIOD_H4:  return("H4");
      case PERIOD_D1:  return("D1");
      default:         return("NA");
     }
  }
//+------------------------------------------------------------------+
void ClearAll()
  {
   for(int i = ObjectsTotal(0, -1, -1) - 1; i >= 0; i--)
     {
      string nm = ObjectName(0, i, -1, -1);
      if(StringFind(nm, PFX) == 0 || StringFind(nm, "AURUM_") == 0)
         ObjectDelete(0, nm);
     }
  }
//+------------------------------------------------------------------+
color TokenColor(string t)
  {
   if(t == "GREEN")  return(clrLime);
   if(t == "RED")    return(clrRed);
   if(t == "BLUE")   return(clrDodgerBlue);
   if(t == "YELLOW") return(clrGold);
   if(t == "WHITE")  return(clrWhite);
   return(clrSilver); // GRAY
  }
ENUM_LINE_STYLE TokenStyle(string s)
  {
   if(s == "DASH") return(STYLE_DASH);
   if(s == "DOT")  return(STYLE_DOT);
   return(STYLE_SOLID);
  }
//+------------------------------------------------------------------+
void MakeLabel(string name, datetime t, double p, string text,
               color clr, string anchor)
  {
   if(ObjectFind(0, name) < 0)
      ObjectCreate(0, name, OBJ_TEXT, 0, t, p);
   ObjectSetInteger(0, name, OBJPROP_TIME, t);
   ObjectSetDouble(0, name, OBJPROP_PRICE, p);
   ObjectSetString(0, name, OBJPROP_TEXT, text);
   ObjectSetInteger(0, name, OBJPROP_COLOR, clr);
   ObjectSetInteger(0, name, OBJPROP_FONTSIZE, 8);
   ObjectSetInteger(0, name, OBJPROP_ANCHOR,
                    anchor == "DOWN" ? ANCHOR_UPPER : ANCHOR_LOWER);
   ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
   ObjectSetInteger(0, name, OBJPROP_HIDDEN, true);
   ObjectSetInteger(0, name, OBJPROP_BACK, false);
  }
//+------------------------------------------------------------------+
void MakeTrend(string name, datetime t1, double p1, datetime t2,
               double p2, color clr, ENUM_LINE_STYLE style, int width)
  {
   if(ObjectFind(0, name) < 0)
      ObjectCreate(0, name, OBJ_TREND, 0, t1, p1, t2, p2);
   ObjectSetInteger(0, name, OBJPROP_TIME, 0, t1);
   ObjectSetDouble(0, name, OBJPROP_PRICE, 0, p1);
   ObjectSetInteger(0, name, OBJPROP_TIME, 1, t2);
   ObjectSetDouble(0, name, OBJPROP_PRICE, 1, p2);
   ObjectSetInteger(0, name, OBJPROP_COLOR, clr);
   ObjectSetInteger(0, name, OBJPROP_STYLE, style);
   ObjectSetInteger(0, name, OBJPROP_WIDTH, width);
   ObjectSetInteger(0, name, OBJPROP_RAY_RIGHT, false);
   ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
   ObjectSetInteger(0, name, OBJPROP_HIDDEN, true);
  }
//+------------------------------------------------------------------+
void MakeHLine(string name, double p, color clr, ENUM_LINE_STYLE style,
               string text)
  {
   if(ObjectFind(0, name) < 0)
      ObjectCreate(0, name, OBJ_HLINE, 0, 0, p);
   ObjectSetDouble(0, name, OBJPROP_PRICE, p);
   ObjectSetInteger(0, name, OBJPROP_COLOR, clr);
   ObjectSetInteger(0, name, OBJPROP_STYLE, style);
   ObjectSetInteger(0, name, OBJPROP_WIDTH, 1);
   ObjectSetInteger(0, name, OBJPROP_BACK, true);
   ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
   ObjectSetInteger(0, name, OBJPROP_HIDDEN, true);
   if(StringLen(text) > 0)
      ObjectSetString(0, name, OBJPROP_TEXT, text);
  }
//+------------------------------------------------------------------+
void MakeRect(string name, datetime t1, double p1, datetime t2,
              double p2, color clr)
  {
   if(t2 <= t1)
      t2 = t1 + SweepBoxBars * PeriodSeconds();
   if(ObjectFind(0, name) < 0)
      ObjectCreate(0, name, OBJ_RECTANGLE, 0, t1, p1, t2, p2);
   ObjectSetInteger(0, name, OBJPROP_TIME, 0, t1);
   ObjectSetDouble(0, name, OBJPROP_PRICE, 0, p1);
   ObjectSetInteger(0, name, OBJPROP_TIME, 1, t2);
   ObjectSetDouble(0, name, OBJPROP_PRICE, 1, p2);
   ObjectSetInteger(0, name, OBJPROP_COLOR, clr);
   ObjectSetInteger(0, name, OBJPROP_FILL, true);
   ObjectSetInteger(0, name, OBJPROP_BACK, true);
   ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
   ObjectSetInteger(0, name, OBJPROP_HIDDEN, true);
  }
//+------------------------------------------------------------------+
void Render()
  {
   string tf = TFString();
   string want = PFX + tf + "_";   // e.g. MS_M15_

   int h = FileOpen(OverlayFile,
                    FILE_READ | FILE_CSV | FILE_COMMON | FILE_ANSI, ',');
   if(h == INVALID_HANDLE)
      return;  // agent not running yet — keep last drawing

   ClearAll();
   int drawn = 0;

   while(!FileIsEnding(h))
     {
      string kind   = FileReadString(h);
      if(StringLen(kind) == 0) break;
      string name   = FileReadString(h);
      datetime t1   = (datetime)StringToInteger(FileReadString(h));
      double   p1   = StringToDouble(FileReadString(h));
      datetime t2   = (datetime)StringToInteger(FileReadString(h));
      double   p2   = StringToDouble(FileReadString(h));
      string colTok = FileReadString(h);
      string styTok = FileReadString(h);
      int    width  = (int)StringToInteger(FileReadString(h));
      string anchor = FileReadString(h);
      string text   = FileReadString(h);

      // only this chart's timeframe
      if(StringFind(name, want) != 0)
         continue;

      color clr = TokenColor(colTok);
      ENUM_LINE_STYLE sty = TokenStyle(styTok);

      if(kind == "LABEL")            MakeLabel(name, t1, p1, text, clr, anchor);
      else if(kind == "TEXT")        MakeLabel(name, t1, p1, text, clr, anchor);
      else if(kind == "TREND")       MakeTrend(name, t1, p1, t2, p2, clr, sty, width);
      else if(kind == "HLINE")       MakeHLine(name, p1, clr, sty, text);
      else if(kind == "RECT")        MakeRect(name, t1, p1, t2, p2, clr);
      drawn++;
     }
   FileClose(h);

   // status stamp (bottom-left)
   string st = "AURUM_STAMP";
   if(ObjectFind(0, st) < 0)
      ObjectCreate(0, st, OBJ_LABEL, 0, 0, 0);
   ObjectSetInteger(0, st, OBJPROP_CORNER, CORNER_LEFT_LOWER);
   ObjectSetInteger(0, st, OBJPROP_XDISTANCE, 8);
   ObjectSetInteger(0, st, OBJPROP_YDISTANCE, 8);
   ObjectSetInteger(0, st, OBJPROP_COLOR, clrAqua);
   ObjectSetInteger(0, st, OBJPROP_FONTSIZE, 8);
   ObjectSetString(0, st, OBJPROP_TEXT,
                   "AURUM AI — Structure Mapping (" + tf + ") — " +
                   (string)drawn + " objects — " +
                   TimeToString(TimeCurrent(), TIME_MINUTES));
   ChartRedraw();
  }
//+------------------------------------------------------------------+
