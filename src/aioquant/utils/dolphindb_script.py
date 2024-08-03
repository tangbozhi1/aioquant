"""
DolphinDB脚本
在DolphinDB中初始化创建数据库和数据表
在DolphinDB中初始化创建流数据及加载历史数据作为流数据回放
常用sql指令封装
"""

# 创建分布式表
CREATE_TABLE_SCRIPT = """
//建库函数 (存在就删除)
def CreateDb(dfsPath){
	if(existsDatabase(dfsPath)){
		dropDatabase(dfsPath)
	}
	dbExchange = database("", HASH, [SYMBOL, 3])
	dbTime = database("", VALUE, 2010.01.01..2023.12.31);
	dbSymbol = database("", HASH, [SYMBOL, 3000])
	dbHandle = database(dfsPath, COMPO, [dbExchange, dbTime, dbSymbol],engine='TSDB')
	return dbHandle
}

//建交易量划分K线窗口函数 (存在就删除)
def CreateBarTable(dbHandle,dfsPath,tableName){
	//表已存在
	if (existsTable(dfsPath,tableName)){
		dbKline=database(dfsPath)
		dbKline.dropTable(tableName)
	}
	kline_columns = `timestamp`start`stop`open`high`low`close`volume`symbol`platform
	kline_type = [TIMESTAMP,TIMESTAMP,TIMESTAMP,DOUBLE,DOUBLE,DOUBLE,DOUBLE,DOUBLE,SYMBOL,SYMBOL]
	tbkline = table(1:0, kline_columns,kline_type)
    bar = dbHandle.createPartitionedTable(tbkline,`bar, `platform`timestamp`symbol,sortColumns=`timestamp)
    return bar
}

//建K线表函数 (存在就删除)
def CreateKlineTable(dbHandle,dfsPath,tableName){
	//表已存在
	if (existsTable(dfsPath,tableName)){
		dbKline=database(dfsPath)
		dbKline.dropTable(tableName)
	}
	kline_columns = `candle_begin_time`open`high`low`close`volume`symbol`kline_type`platform
	kline_type = [TIMESTAMP,DOUBLE,DOUBLE,DOUBLE,DOUBLE,DOUBLE,SYMBOL,SYMBOL,SYMBOL]
	tbkline = table(1:0, kline_columns,kline_type)
    kline = dbHandle.createPartitionedTable(tbkline,`kline, `platform`candle_begin_time`symbol,sortColumns=`candle_begin_time)
    return kline
}

//建Tick表函数 (存在就删除)
def CreateTickTable(dbHandle,dfsPath,tableName){
	//表已存在
	if (existsTable(dfsPath,tableName)){
		dbTick=database(dfsPath)
		dbTick.dropTable(tableName)
	}
	tick_columns = `ask`bid`last`timestamp`symbol`platform
	tick_type = [STRING,STRING,STRING,TIMESTAMP,SYMBOL,SYMBOL]
	tbtick = table(1:0, tick_columns,tick_type)
    tick = dbHandle.createPartitionedTable(tbtick,`tick, `platform`timestamp`symbol,sortColumns=`timestamp)
    return tick
}

//建Trade表函数 (存在就删除)
def CreateTradeTable(dbHandle,dfsPath,tableName){
	//表已存在
	if (existsTable(dfsPath,tableName)){
		dbTrade=database(dfsPath)
		dbTrade.dropTable(tableName)
	}
	trade_columns = `action`id`price`quantity`timestamp`symbol`platform
	trade_type = [SYMBOL,SYMBOL,DOUBLE,DOUBLE,TIMESTAMP,SYMBOL,SYMBOL]
	tbtrade = table(1:0, trade_columns,trade_type)
    trade = dbHandle.createPartitionedTable(tbtrade,`trade, `platform`timestamp`symbol,sortColumns=`timestamp)
    return trade
}

//建Orderbook表函数 (存在就删除)
def CreateOrderbookTable(dbHandle,dfsPath,tableName){
	//表已存在
	if (existsTable(dfsPath,tableName)){
		dbOrderbook=database(dfsPath)
		dbOrderbook.dropTable(tableName)
	}
	orderbook_columns = `asks`bids`timestamp`symbol`platform
	orderbook_type = [STRING,STRING,TIMESTAMP,SYMBOL,SYMBOL]
	tborderbook = table(1:0, orderbook_columns,orderbook_type)
    orderbook = dbHandle.createPartitionedTable(tborderbook,`orderbook,`platform`timestamp`symbol,sortColumns=`timestamp)
    return orderbook
}
"""
# 内存表格式转换（变量为array数组列表,如果不是需要在python中np.array对单个列提前转换)
# msgs = [msg.decode('UTF-8') for msg in msgs]  字节转JSON STR
# msgs = [eval(msg) for msg in msgs]  JSON转DICT (eval对单双引号处理)
# platform = np.array([msg['platform'] for msg in msgs])  用np.array转数组
# symbol = [msg['symbol'] for msg in msgs]                因为有[]也可不转
# open = [float(msg['open']) for msg in msgs]             转类型为FLOAT
# timestamp = [int(msg['timestamp']) for msg in msgs]     转类型为INT，后面转Dolphindb时要先转长整型LONG再转时间TIMESTAMP，不然会默认类型出错
# ask = [str(msg['ask']) for msg in msgs]                 转类型为STR，不然里边是JSON会类型出错
# last = [str(msg['last']) for msg in msgs]               转类型为STR，里边last=None
# s.upload({'last': last})                                上传到服务器变量名last，类型为字符型向量
TABLE_CONVERS_SCRIPT = """
kline_table = table(timestamp(long(timestamp)) as candle_begin_time,open,high,low,close,volume,symbol,kline_type,platform)
tick_table = table(ask,bid,last,timestamp(long(timestamp)) as timestamp,symbol,platform)
trade_table = table(action,id,price,quantity,timestamp(long(timestamp)) as timestamp,symbol,platform)
orderbook_table = table(asks,bids,timestamp(long(timestamp)) as timestamp,symbol,platform)
"""

INIT_STREAM_SCRIPT = """
//清理所有流引擎
def dropAllStreamEngines(){
	engineStatus=getStreamEngineStat()
	allCurrrentEngineTypes=engineStatus.keys()
	for(eachEngineType in allCurrrentEngineTypes){
		engineInfoTable=engineStatus[eachEngineType]
		for (eachEngineName in engineInfoTable.name){
			try{
				dropStreamEngine(eachEngineName)
				print("注销引擎",eachEngineName,"成功")
			}
			catch(ex){
				print("注销引擎",eachEngineName,"失败:",ex)
			}
		}
	}
}

//取消所有订阅
def unsubscribeAll(){
	streamStat=getStreamingStat()//检查流状态
	pubTables=streamStat["pubTables"]
	unsubTablesDict=dict(pubTables.tableName,pubTables.actions)
	for(eachTableName in unsubTablesDict.keys()){
		print(eachTableName)
		allActionsString=unsubTablesDict[eachTableName]
		allActionsString=strReplace(allActionsString,"]","")
		allActionsString=strReplace(allActionsString,"[","")
		allActionNames=allActionsString.split(",")
		for(eachActionName in allActionNames){
			print(eachActionName)
			try{
				unsubscribeTable(tableName=eachTableName,actionName=eachActionName)
				输出日志="共享表:"+eachTableName+",action:"+eachActionName+",已解除订阅"
				print(输出日志)
			}
			catch(ex){
				print("解除订阅失败:\r\n",ex)
				print(eachTableName)
				print(eachActionName)
				print(eachActionName)
			}
		}
	}
}

//清除所有共享表
def removeAllSharedTable(){
	allSharedObjects=exec name from objs(true) where shared==true
	for (eachSharedTable in allSharedObjects){
		try{
			dropStreamTable(eachSharedTable)
			//undef(eachSharedTable,SHARED)
			日志提示="共享表:"+eachSharedTable+",已析构"
			print(日志提示)
		}	
		catch(ex){
			日志提示="共享表:"+eachSharedTable+",析构失败,提示:"
			print(日志提示,ex)		
		}
	}
}

//执行流清理函数
unsubscribeAll()//解除订阅
dropAllStreamEngines()//删引擎
removeAllSharedTable()//删流表
go;
"""

SYNTHETIC_K_SCRIPT = """
// 使用TRADE数据合成1分钟K线
tbColNames = `action`id`price`quantity`timestamp`symbol`platform
tbColTypes = [SYMBOL,SYMBOL,DOUBLE,DOUBLE,TIMESTAMP,SYMBOL,SYMBOL]
//建空流表
tbTrades = streamTable(100000:0,tbColNames,tbColTypes)
//流数据表持久化
enableTableShareAndPersistence(table=tbTrades, tableName=`trades, cacheSize=2000000, retentionMinutes=4320)
//共享K线流表
barColNames = `candle_begin_time`open`high`low`close`volume`symbol`kline_type`platform
barColTypes = [TIMESTAMP,DOUBLE,DOUBLE,DOUBLE,DOUBLE,DOUBLE,SYMBOL,SYMBOL,SYMBOL]
share streamTable(100:0, barColNames, barColTypes) as klines
metrics=<[
first(price),
max(price),
min(price),
last(price),
sum(-quantity if action == "SELL" else quantity),
last(timestamp)]>
//聚合引擎
tsAggrKline = createTimeSeriesAggregator(name="aggr_kline_min01", windowSize=600000, step=600000, metrics=metrics, dummyTable=trades, outputTable=klines, timeColumn=`timestamp, keyColumn=`symbol,updateTime=500, useWindowStartTime=true)
//订阅 
subscribeTable(tableName="trades", actionName="aggr_kline_min01", offset=-1, handler=append!{getStreamEngine("aggr_kline_min01")}, batchSize=1000, throttle=1, hash=0, msgAsTable=true)
"""

TICK_REPLAY_SCRIPT = """
//重复运行时清理环境
def clearEnv(){
	try{
	dropAggregator(`tsAggr1)
	dropAggregator(`tsAggr2)
	unsubscribeTable(,`level2,`act_tsAggr1)
	unsubscribeTable(,`level2,`act_tsAggr2)
	unsubscribeTable(,`level2,`act_factor)
	unsubscribeTable(,`level2,`newestLevel2data)
	undef(`level2,SHARED)
	undef(`OHLC1,SHARED)
	undef(`OHLC2,SHARED)
	undef(`FACTOR,SHARED)
	}catch(ex){}
	
}
clearEnv()
share streamTable(100:0, `askPrice1`bidPrice1`askVolume1`bidVolume1`last`timestamp`symbol`platform,[DOUBLE,DOUBLE,DOUBLE,DOUBLE,DOUBLE,TIMESTAMP,SYMBOL,SYMBOL]) as level2
dbPath = "dfs://level2Replay"
//使用回放功能将数据写入流表发布
dbDate = database("", VALUE, 2010.01.01..2023.12.31)
dbSymbol=database("", HASH, [SYMBOL, 10])
if(existsDatabase(dbPath)){
	dropDatabase(dbPath)
}
db = database(dbPath, COMPO, [dbDate, dbSymbol])
modal = table(1:0, `askPrice1`bidPrice1`askVolume1`bidVolume1`last`timestamp`symbol`platform,[DOUBLE,DOUBLE,DOUBLE,DOUBLE,DOUBLE,TIMESTAMP,SYMBOL,SYMBOL])
pt=db.createPartitionedTable(modal,`quotes, `timestamp`symbol)
data = select askPrice1,bidPrice1,askVolume1,bidVolume1,last,timestamp,symbol,platform from loadTable("dfs://level2","quotes")
pt.append!(data)
quotes = loadTable(dbPath,"quotes")
//设置每次提取到内存数据量=1小时
repartitionSchema = time(cutPoints(08:00:00..18:00:00,10))
inputDS = replayDS(<select * from quotes>, `datetime, `datetime,  repartitionSchema)
submitJob("replay_quotes", "replay_quotes_stream",  replay,  [inputDS],  [`level2], `datetime, `datetime, 10, false, 2)
"""

STREAM_REPLAY_SCRIPT = """
//删除数据文件第一行无关信息,另存到-processes目录
def dataPreProcess(DIR){
	if(!exists(DIR+ "-processed/"))
		mkdir(DIR+ "-processed/")
	fileList = exec filename from files(DIR) where isDir = false, filename like "%.csv"
	for(filename in fileList){
		f = file(DIR + "/" + filename)
		y = f.readLines(1000000).removeHead!(1)
		saveText(y, DIR+ "-processed/" + filename)
	}
}
//创建数据库
def CreateReplayDB(dfsPath){
	if(existsDatabase(dfsPath)){
		dropDatabase(dfsPath)
	}
	dbTime = database("", VALUE, 2010.01.01..2023.12.31);
	dbSymbol = database("", HASH, [SYMBOL, 3000])
	dbHandle = database(dfsPath, COMPO, [dbTime, dbSymbol],engine='TSDB')
	tick_columns = `ask`bid`last`timestamp`symbol`platform
	tick_type = [STRING,STRING,STRING,TIMESTAMP,SYMBOL,SYMBOL]
	tbtick = table(100:0, tick_columns,tick_type)
    tick = dbHandle.createPartitionedTable(tbtick,`tick, `platform`timestamp`symbol,sortColumns=`timestamp)
	orderbook_columns = `asks`bids`timestamp`symbol`platform
	orderbook_type = [STRING,STRING,TIMESTAMP,SYMBOL,SYMBOL]
	tborderbook = table(100:0, orderbook_columns,orderbook_type)
    orderbook = dbHandle.createPartitionedTable(tborderbook,`orderbook,`platform`timestamp`symbol,sortColumns=`timestamp)
    return tick, orderbook
}
// 将csv文本数据导入数据库
def loadTick(path, filename, mutable tb){
	tmp = filename.split("_")
	product = tmp[1]
	file = path + "/" + filename
	t = loadText(file)
	t[`product]=product
	tb.append!(t)
}

def loopLoadTick(mutable tb, path){
	fileList = exec filename from files(path,"%.csv")
	for(filename in fileList){
		print filename
		loadTick(path, filename, tb)
	}
}


def loadOrderBook(path, filename, mutable tb){
	tmp = filename.split("_")
	product = tmp[1]
	file = path + "/" + filename
	t = loadText(file)
	t[`product] = product
	tb.append!(t)
}

def loopLoadOrderBook(mutable tb, path){
	fileList = exec filename from files(path, "%.csv")
	for(filename in fileList){
		print filename
		loadOrderBook(path, filename, tb)
	}
}

//导入数据使用示例：
//tick, orderbook = CreateReplayDB("dfs://digital")
//假设csv在目录/hdd/data/orderBook，/hdd/data/ordertick并且第一行要删除
//loopLoadOrderBook(orderbook, "/hdd/data/orderBook-processed")
//loopLoadTick(tick, "/hdd/data/tick-processed")

//定义数据回放函数
def replayData(dfsPath, productCode, startTime, length, rate){
    tick = loadTable(dfsPath, 'tick');
    orderbook = loadTable(dfsPath, 'orderbook');

	schTick = select name,typeString as type from  tick.schema().colDefs;
	schOrderBook = select name,typeString as type from  orderbook.schema().colDefs;
	
    share(streamTable(100:0, schOrderBook.name, schOrderBook.type), `outOrder);
    share(streamTable(100:0, schTick.name, schTick.type), `outTick);
    enableTablePersistence(objByName(`outOrder), true,true, 100000);
    enableTablePersistence(objByName(`outTick), true,true, 100000);
    clearTablePersistence(objByName(`outOrder));
    clearTablePersistence(objByName(`outTick));
                                                
    share(streamTable(100:0, schOrderBook.name, schOrderBook.type), `outOrder);
    share(streamTable(100:0, schTick.name, schTick.type), `outTick);
    enableTablePersistence(objByName(`outOrder), true,true, 100000);
    enableTablePersistence(objByName(`outTick), true,true, 100000);

	endTime = temporalAdd(startTime, length, "m")
    sqlTick = sql(sqlCol("*"), tick,  [<product=productCode>, <timestamp between timestamp(pair(startTime, endTime))>]);
    sqlOrder = sql(sqlCol("*"), orderbook,  [<product=productCode>, <timestamp between timestamp(pair(startTime, endTime))>]);
    cutCount = length * 60 / 20
    trs = cutPoints(timestamp(startTime..endTime), cutCount);
    rds = replayDS(sqlTick, `timestamp , , trs);
    rds2 = replayDS(sqlOrder, `timestamp , , trs);
    return submitJob('replay_digital','replay_digital',  replay,  [rds,rds2],  [`outTick,`outOrder],`timestamp ,, rate);
}

addFunctionView(replayData);

//数据回放使用示例：
//下载数据回放界面的html压缩包https://github.com/dolphindb/applications/raw/master/cryptocurr_replay/replay.zip
//将replay.zip解压到DolphinDB程序包的web目录
//在浏览器地址栏中输入http://[host]:[port]/replay.html打开数据回放界面
//这里的host和port是指数据节点的IP地址和端口号，如http://192.168.1.135:8902/replay.html。
//数据回放前，我们可以设置以下参数：
//    Product：加密货币代码
//    Replay Rate：回放速度，即每秒钟回放的记录数。如果市场每秒钟产生100笔交易，Replay Rate设置为1000就以10倍的速度回放。
//    Start Time：数据的起始时间
//    Length：数据的时间跨度，单位是分钟。如果Start Time设置为2018.09.17 00:00:00，Length设置为60，表示回放的数据是在2018.09.17 00:00:00-2018.09.17 00:59:59之间产生的。
"""

SQL_SCRIPT = """
//K线计算相关
//内置函数:
//bar取整点
//    date = 09:32m 09:33m 09:45m 09:49m 09:56m 09:56m;
//    bar(date, 5);
//    [09:30m,09:30m,09:45m,09:45m,09:55m,09:55m]
//dailyAlignedBar指定每个交易时段起始时刻
//wj计算重叠K线窗口,每5分钟计算30分钟K线
//计算5分钟K线:
barMinutes = 5
OHLC5 = select first(price) as open, max(price) as high, min(price) as low, last(price) as close, sum(quantity) as volume from trade group by symbol, bar(timestamp, barMinutes*60*1000) as barStart
barMinutes = 7
OHLC7 = select first(price) as open, max(price) as high, min(price) as low, last(price) as close, sum(quantity) as volume from trade group by symbol, dailyAlignedBar(timestamp, 09:30:00.000, barMinutes*60*1000) as barStart
//两个时段
barMinutes = 7
sessionsStart=09:30:00.000 13:00:00.000
OHLC_7 = select first(price) as open, max(price) as high, min(price) as low, last(price) as close, sum(quantity) as volume from trade group by symbol, dailyAlignedBar(timestamp, sessionsStart, barMinutes*60*1000) as barStart
//交易量划分K线窗口
volThreshold = 1000000
OHLC_vol = select first(timestamp) as barStart, first(price) as open, max(price) as high, min(price) as low, last(price) as close, last(cumvol) as cumvol from (select symbol, time, price, cumsum(quantity) as cumvol from trade context by symbol) group by symbol, bar(cumvol, volThreshold) as volBar
//重叠K线(每5分钟计算30分钟K线)
barWindows = table(symbol.cj(table((09:30:00.000 + 0..23 * 300000).join(13:00:00.000 + 0..23 * 300000) as timestamp))
OHLC_C = wj(barWindows, trade, 0:(30*60*1000), <[first(price) as open, max(price) as high, min(price) as low, last(price) as close, sum(quantity) as volume]>, `symbol`timestamp)
"""

"""
Python 示例
示例1：开启API数据节点异步高可用(无返回值只能s.run("")运行)
import dolphindb as ddb
s = ddb.session(enableASYNC=True)
sites=["192.168.1.2:24120", "192.168.1.3:24120", "192.168.1.4:24120"]
s.connect(host="192.168.1.2", port=24120, userid="admin", password="123456", highAvailability=True, highAvailabilitySites=sites)

示例2：运行脚本(脚本在 DolphinDB 中返回对象，会转换成 Python 中对象)
a=s.run("`IBM`GOOG`YHOO")

示例3: 运行脚本(带参数)
script='''
def getTypeStr(input){
    return typestr(input)
}
'''
s.run(script)
s.run("getTypeStr", 1)

示例4: 上传数据
客户端上传参数的数据结构可以是标量 (scalar)，列表 (list)，字典 (dict)，NumPy ,DataFrame,Series,时间要转numpy.datetime64类型
不同数据类型的list会被识别为元组（any vector）最好使用 np.array 代替 list，例如a=np.array([1,2,3.0],dtype=np.double)
s.upload({'a': df})
s.run('a') //会打印df

示例5: table 方法上传(字典、DataFrame 或 DolphinDB 中的表名)
s.table(data=df, tableAliasName="a")
print(s.loadTable("a").toDF())  //会打印df

示例6: 上传数据到DFS分区表然后下载到内存
db = database("dfs://testdb",RANGE, [1, 5 ,11])
t1=table(1..10 as id, 1..10 as v)
db.createPartitionedTable(t1,`t1,`id).append!(t1)
pt1=s.loadTable(tableName='t1',dbPath="dfs://testdb")

示例7: 导入内存表（返回的 DolphinDB 表对象转化为 pandas DataFrame）
trade=s.loadText(WORK_DIR+"/example.csv")
df = trade.toDF()

示例8: 导入 DFS 分区表（大表)
import dolphindb.settings as keys
s.database(dbName='mydb', partitionType=keys.VALUE, partitions=['AMZN','NFLX', 'NVDA'], dbPath='dfs://valuedb')
# 等效于 mydb = s.run("db=database('dfs://valuedb', VALUE, ['AMZN','NFLX','NVDA'])")
trade = s.loadTextEx(dbPath="mydb", tableName='trade',partitionColumns=["TICKER"], remoteFilePath=WORK_DIR + "/example.csv")
#展示表的结构：
print(trade.schema)
df = trade.toDF()

示例9：分布式表的并发写入
pool = ddb.DBConnectionPool("localhost", 8848, 20, "admin", "123456")
appender = ddb.PartitionedTableAppender("dfs://valuedb", "pt", "id", pool)
re = appender.append(data)

示例14：追加数据到分布式表
database 函数用于创建数据库
createPartitionedTable 函数用于创建分区表
t.append!(t1) t1数据表，t为分区表
s.run("tableInsert{{loadTable('{db}', `{tb})}}".format(db=dbPath,tb=tableName), df) 追加数据，先loadTable再tableInsert
s.run("append!{{loadTable('{db}', `{tb})}}".format(db=dbPath,tb=tableName),df) 最好用上面代码
appender = ddb.tableAppender("dfs://tableAppender","pt", s)  三种方法追加，都是自动类型转换
appender.append(df)

示例10：从 DolphinDB 数据库中加载数据
trade = s.loadTable(tableName="trade",dbPath="dfs://valuedb")
print(trade.schema)
print(trade.toDF())

示例11：从 DolphinDB 数据库中加载数据SQL 语句过滤
s.database(dbName='mydb', partitionType=keys.VALUE, partitions=["AMZN","NFLX", "NVDA"], dbPath="dfs://valuedb")
t = s.loadTextEx(dbPath="mydb",  tableName='trade',partitionColumns=["TICKER"], remoteFilePath=WORK_DIR + "/example.csv")  #内存不足，example.csv先入数据库
trade = s.loadTableBySQL(tableName="trade", dbPath="dfs://valuedb", sql="select * from trade where date>2010.01.01")
print(trade.rows)

示例12：追加数据到内存表
s.run("share t as tglobal")  //共享内存表以便多个客户端同时访问内存表
args = [ids, dates, tickers, prices]
s.run("tableInsert{tglobal}", args)
s.run("tableInsert{tglobal}",tb)

示例13：内存表追加数据
appender = ddb.tableAppender(tableName="t", ddbSession=s)  //tableAppender 对象追加数据时自动转换时间类型
re = appender.append(data)
upsert = ddb.tableUpsert("","ttable",s)   //同 tableAppender类似
re = upsert.upsert(df)

示例15：update 更新内存表
trade=s.loadText(WORK_DIR+"/example.csv")
trade = trade.update(["VOL"],["999999"]).where("TICKER=`AMZN").where(["date=2015.12.16"]).execute()

示例16：update 更新分布式表
t1=s.loadTable(tableName="pt",dbPath=dbPath)
t1.update(["price"],["11"]).where("sym=`AMZN").execute()

示例17：delete删除内存表中的记录
trade=s.loadText(WORK_DIR+"/example.csv")
trade.delete().where('date<2013.01.01').execute()

示例18：delete删除分布式表中的记录
t1=s.loadTable(tableName="pt",dbPath=dbPath)
t1.delete().where("sym=`AMZN").execute()

示例19：drop删除内存表中的列
trade=s.loadText(WORK_DIR+"/example.csv")
t1=trade.drop(['ask', 'bid'])

示例20：dropTable删除分布式表(都是先load到内存再操作)
s.loadTextEx(dbPath="dfs://valuedb", partitionColumns=["TICKER"], tableName='trade', remoteFilePath=WORK_DIR + "/example.csv")
s.dropTable(dbPath="dfs://valuedb", tableName="trade")


SQL查询系列
select
trade=s.loadText(WORK_DIR+"/example.csv")
trade.select(['ticker','date','bid','ask','prc','vol']).toDF()   .showSQL()展示sql语句
trade.select("ticker,date,bid,ask,prc,vol").where("date=2012.09.06").where("vol<10000000").toDF()

exec 
select 子句总是生成一张表，exec 生成一个标量或者一个向量
trade = s.loadTextEx(dbPath="dfs://valuedb", partitionColumns=["TICKER"], tableName='trade', remoteFilePath=WORK_DIR + "/example.csv")
trade.exec('ticker').toDF()
trade.exec(['ticker','date','bid','ask','prc','vol']).toDF() 生成DataFrame

top & limit
tb = s.loadTable(dbPath="dfs://valuedb", tableName="trade")
t1 = tb.select("*").contextby('ticker').limit(-2)
t1 = tb.select("*").limit([2, 5])

where 
t1=trade.select(['date','bid','ask','prc','vol']).where('TICKER=`AMZN').where('bid!=NULL').where('ask!=NULL').where('vol>10000000').sort('vol desc').executeAs("t1")
select 的输入内容可以是包含多个列名的字符串，where 的输入内容可以是包含多个条件的字符串。
trade.select("ticker, date, vol").where("bid!=NULL, ask!=NULL, vol>50000000").toDF()

groupby
要使用聚合函数count, sum, agg 或 agg2 
trade.select(['sum(vol)','sum(prc)']).groupby(['ticker']).toDF()
trade.select('count(ask)').groupby(['vol']).having('count(ask)>1').toDF()

contextby
groupby 为每个组返回一个标量，但是 contextby 为每个组返回一个向量
df= s.loadTable(tableName="trade",dbPath="dfs://valuedb").contextby('ticker').top(3).toDF()
df= s.loadTable(tableName="trade",dbPath="dfs://valuedb").select("TICKER, month(date) as month, cumsum(VOL)").contextby("TICKER,month(date)").toDF()
df= s.loadTable(dbPath="dfs://valuedb", tableName="trade").contextby('ticker').having("sum(VOL)>40000000000").toDF()
df = s.loadTable(dbPath="dfs://valuedb", tableName="trade").contextby('ticker').csort('date desc').toDF()  使用 csort 关键字排序(指定 asc 和 desc 关键字来决定排序顺序)
sort(by, ascending=True)
csort(by, ascending=True)
t1 = tb.select("*").contextby('ticker').csort(["TICKER", "VOL"], True).limit(5)
t1 = tb.select("*").contextby('ticker').csort(["TICKER", "VOL"], [True, False]).limit(5)

pivotby
表中一列或多列的内容按照两个维度重新排列
df.select("VOL").pivotby("TICKER", "date").toDF()   pivotby 与 select 子句一起使用时返回一个表
df.exec("VOL").pivotby("TICKER", "date").toDF()     pivotby 和 exec 语句一起使用时返回一个 dolphindb 的矩阵对象

merge
内部连接 (ej)、左连接 (lj)、左半连接 (lsj) 和外部连接 (fj)，merge_asof 为 asof join，merge_window 为窗口连接
on 参数指定连接列，如果连接列名称不同，使用 left_on 和 right_on 参数指定连接列
trade.merge(t1,on=["TICKER","date"]).toDF()
trade.merge(t1,left_on=["TICKER","date"], right_on=["TICKER1","date1"]).toDF()
trade.merge(t1,how="left", on=["TICKER","date"]).where('TICKER=`AMZN').where('2015.12.23<=date<=2015.12.31').toDF()
t1.merge(t2, how="outer", on=["TICKER","date"]).toDF()

merge_asof
对应 DolphinDB 中的 asof join (aj)
trades.merge_asof(quotes,on=["Symbol","Time"]).select(["Symbol","Time","Trade_Volume","Trade_Price","Bid_Price", "Bid_Size","Offer_Price", "Offer_Size"]).top(5).toDF()

merge_window
对应 DolphinDB 中的 window join(wj)
trades.merge_window(quotes, -5000000000, 0, aggFunctions=["avg(Bid_Price)","avg(Offer_Price)"], on=["Symbol","Time"]).where("Time>=07:59:59").top(10).toDF()


流数据操作
from threading import Event
import dolphindb as ddb
import pandas as pd
import numpy as np
s = ddb.session()
s.enableStreaming(8000)
//s.subscribe(host, port, handler, tableName, actionName="", offset=-1, resub=False, filter=None, msgAsTable=False, [batchSize=0], [throttle=1], [userName=""],[password=""], [streamDeserializer=None])
def handler(lst):
    print(lst)
s.subscribe("192.168.1.103",8921,handler,"trades","action",0,False,np.array(['000905']),)
# 订阅DolphinDB(本机8848端口)上的OHLC流数据表
s.subscribe("127.0.0.1", 8848, handler, "OHLC","python_api_subscribe",0)
Event().wait() 

//s.unsubscribe(host,port,tableName,actionName="")
s.unsubscribe("192.168.1.103", 8921,"trades","action")
异构流表反序列化器
sd = streamDeserializer(sym2table, session=None)

示例1：
构造一个异构流表
// 构造输出流表
share streamTable(100:0, `timestampv`sym`blob`price1,[TIMESTAMP,SYMBOL,BLOB,DOUBLE]) as outTables
// 构造数据库和原始数据表
n = 10;
dbName = 'dfs://test_StreamDeserializer_pair'
db = database(dbName,RANGE,2012.01.01 2013.01.01 2014.01.01 2015.01.01 2016.01.01 2017.01.01 2018.01.01 2019.01.01)
table1 = table(100:0, `datetimev`timestampv`sym`price1`price2, [DATETIME, TIMESTAMP, SYMBOL, DOUBLE, DOUBLE])
table2 = table(100:0, `datetimev`timestampv`sym`price1, [DATETIME, TIMESTAMP, SYMBOL, DOUBLE])
table3 = table(100:0, `datetimev`timestampv`sym`price1, [DATETIME, TIMESTAMP, SYMBOL, DOUBLE])
//添加数据
tableInsert(table1, 2012.01.01T01:21:23 + 1..n, 2018.12.01T01:21:23.000 + 1..n, take(`a`b`c,n), rand(100,n)+rand(1.0, n), rand(100,n)+rand(1.0, n))
tableInsert(table2, 2012.01.01T01:21:23 + 1..n, 2018.12.01T01:21:23.000 + 1..n, take(`a`b`c,n), rand(100,n)+rand(1.0, n))
tableInsert(table3, 2012.01.01T01:21:23 + 1..n, 2018.12.01T01:21:23.000 + 1..n, take(`a`b`c,n), rand(100,n)+rand(1.0, n))
// 三种方式（分区表、流表、内存表）获得表结构定义
pt1 = db.createPartitionedTable(table1,'pt1',`datetimev).append!(table1)
share streamTable(100:0, `datetimev`timestampv`sym`price1, [DATETIME, TIMESTAMP, SYMBOL, DOUBLE]).append!(table2) as pt2
share table3 as pt3
// 构造异构流表
d = dict(['msg1', 'msg2', 'msg3'], [table1, table2, table3])
replay(inputTables=d, outputTables=`outTables, dateColumn=`timestampv, timeColumn=`timestampv)

# 构造异构流表反序列化器(python客户端)
from threading import Event

def streamDeserializer_handler(lst):				# 异构流表反序列化器返回的数据末尾为异构流表反序列化器中 sym2table 指定的 key
    if lst[-1]=="msg1":
        print("Msg1: ", lst)
    elif lst[-1]=='msg2':
        print("Msg2: ", lst)
    else:
        print("Msg3: ", lst)

s = ddb.session("192.168.1.103", 8921, "admin", "123456")
s.enableStreaming(10020)
sd = ddb.streamDeserializer({
    'msg1': ["dfs://test_StreamDeserializer_pair", "pt1"],	# 填入分区表数据库路径和表名的 list，以获取对应表结构
    'msg2': "pt2",						# 填入流表表名
    'msg3': "pt3",						# 填入内存表表名
}, session=s)						     	# 如未指定，则在订阅时获取当前 session
s.subscribe(host="192.168.1.103", port=8921, handler=streamDeserializer_handler, tableName="outTables", actionName="action", offset=0, resub=False,
            msgAsTable=False, streamDeserializer=sd, userName="admin", password="123456")
Event().wait()


示例2：
import dolphindb as ddb
import pandas as pd
import numpy as np
csv_file = "trades.csv"
csv_data = pd.read_csv(csv_file, dtype={'Symbol':str} )
csv_df = pd.DataFrame(csv_data)
s = ddb.session();
s.connect("127.0.0.1",8848,"admin","123456")
#上传DataFrame到DolphinDB，并对Datetime字段做类型转换
s.upload({"tmpData":csv_df})
s.run("data = select Symbol, datetime(Datetime) as Datetime, Price, Volume from tmpData")
s.run("tableInsert(Trade,data)")
s.run("share streamTable(100:0, `datetime`symbol`open`high`low`close`volume,[DATETIME,SYMBOL,DOUBLE,DOUBLE,DOUBLE,DOUBLE,LONG]) as OHLC1")
s.run(tsAggr1 = createTimeSeriesAggregator(name="tsAggr1", windowSize=300, step=300, metrics=<[first(Price),max(Price),min(Price),last(Price),sum(volume)]>, dummyTable=Trade, outputTable=OHLC1, timeColumn=`Datetime, keyColumn=`Symbol)")
s.run("subscribeTable(tableName="Trade", actionName="act_tsAggr1", offset=0, handler=append!{tsAggr1}, msgAsTable=true)")

# (python客户端)
from threading import Event
import dolphindb as ddb
import pandas as pd
import numpy as np
s=ddb.session()
#设定本地端口20001用于订阅流数据
s.enableStreaming(20001)
def handler(lst):         
    print(lst)
# 订阅DolphinDB(本机8848端口)上的OHLC流数据表
s.subscribe("127.0.0.1", 8848, handler, "OHLC","python_api_subscribe",0)
Event().wait() 
"""

"""
orca指南
import numpy as np
import dolphindb.orca as pd
pd.connect("localhost", 8848, "admin", "123456")

创建一个orca Series对象
s = orca.Series([1, 3, 5, np.nan, 6, 8])
创建orca DataFrame对象
df = orca.DataFrame(df)
把一个orca DataFrame转换成pandas DataFrame
pdf = df.to_pandas()
数据类型限制：列中的元素仅可为Python内置的int, float, string等标量类型，不可为Python内置的list, dict等对象
pandas的空值是用浮点数的NaN表示
df=pd.read_table("dfs://stocks","pt") 
必须将其中的NaN改为Python的空字符串("")
df = pd.DataFrame({"str_col": ["hello", "world", np.nan]})
odf = orca.DataFrame(df.fillna({"str_col": ""}))
列的数据类型无法修改,无法添加新的列,无法通过update函数将一个向量赋值给一个列,不支持inplace参数
df = orca.read_table("dfs://orca", "tb")
df.set_index(["date", "symbol"], inplace=True)  # happens on the client side, not on the server side
total = df["price"] * df["amount"]     # The DFS table is not loaded into memory. Calculation has not happened yet. 
total_group_by_symbol = total.groupby(level=[0,1], lazy=True).sum()
pandas中，groupby后调用shift, cumsum, bfill等函数
DolphinDB中的context by语句与move, cumsum, bfill等函数
pandas:
df.groupby("symbol")["prc"].shift(1)
orca:
df.groupby("symbol")["prc"].shift(1).compute()
pandas:
df.groupby("symbol")["prc"].transform(lambda x: x - x.mean())
orca中可改写为：
df.groupby("symbol")["prc"].transform("(x->x - x.mean())").compute()
pandas:
df[(df.x > 0) & (df.y < 0)]
orca:
df[(df.x > 0), (df.y < 0)]
"""