from sigfox_messages import models
from telebot.async_telebot import AsyncTeleBot
from telebot import types
import asyncio
from asgiref.sync import sync_to_async, async_to_sync
from multiprocessing import Process
# import sys


TOKEN_FILE = "token_id"
with open(TOKEN_FILE, 'r') as file:
  token_id = file.read()

bot = AsyncTeleBot(token_id)

goodbye_msg = "Thanks for using Monitor Service."
help_message = "Please issue '/help' command to get interactive help"
stop_broadcast_msg = "In order to interact with me, you must first stop alert broadcasting to this phone "
stop_broadcast_msg += "for the current emergencies to be marked as 'Received', so please issue '/stop' command"

help_list = """

1) Register this telephone to get the emergency notifications:\n'/start' command
2) Stop all alerts to this telephone for the current emergencies:\n'/stop' command
3) Enable/Disable SMS alert messages on this phone:\n'/SMS' command
4) Follow up more patients on this phone:\n'/add' command
5) Stop following a specific patient\n'/unfollow' command
6) Erase this number from Monitor Service:\n'/del' command
7) Show patients linked to this phone and SMS configuration:\n'/show' command
8) Get this help message:\n'/help' command
9) Exit this dialogue:\n'/exit' command

Please type the operation's number or related command: """

SPAWN_CONFIG = "SPAWN_CONFIG"
ALERTING = "ALERTING"
WAIT_CONTACT = "WAIT_CONTACT"
WAIT_NAME_INPUT = "WAIT_NAME_INPUT"
WAIT_PATIENT_CONFIRM = "WAIT_PATIENT_CONFIRM"
WAIT_DNI_INPUT = "WAIT_DNI_INPUT"
WAIT_SMS_OPTION = "WAIT_SMS_OPTION"
WAIT_SMS_CONF = "WAIT_SMS_CONF"
WAIT_UNFOLLOW_OPTION = "WAIT_UNFOLLOW_OPTION"
WAIT_DEL_CONF = "WAIT_DEL_CONF"
WAIT_HELP_OPTION = "WAIT_HELP_OPTION"

input_states = [WAIT_CONTACT, WAIT_NAME_INPUT, WAIT_PATIENT_CONFIRM, WAIT_DNI_INPUT,
                WAIT_SMS_OPTION, WAIT_SMS_CONF, WAIT_DEL_CONF, WAIT_UNFOLLOW_OPTION,
                WAIT_HELP_OPTION]
wait_name_dict = {}
wait_del_dict = {}
wait_unfollow_dict = {}


def my_get_attr(obj, attr):
  return getattr(obj, attr)

def my_set_attr(obj, attr, attr_value):
  return setattr(obj, attr, attr_value)

async_my_get_attr = sync_to_async(my_get_attr, thread_sensitive=True)
async_my_set_attr = sync_to_async(my_set_attr, thread_sensitive=True)

async def send_message(echat_id, text):
  await bot.send_message(echat_id, text)

async def send_location(echat_id, latitude, longitude):
  await bot.send_location(echat_id, latitude, longitude)

async_Patient_Contact_filter = sync_to_async(models.Patient_Contact.objects.filter, thread_sensitive=True)
async_Device_History_filter = sync_to_async(models.Device_History.objects.filter, thread_sensitive=True)
async_Emergency_Payload_filter = sync_to_async(models.Emergency_Payload.objects.filter, thread_sensitive=True)


@bot.message_handler(commands=["stop"])
async def handle_stop_command(message):

  stop_err = 0
  try:
   contact = await models.Contact.objects.aget(echat_id=message.chat.id)
   if (contact.echat_state != ALERTING):
     stop_err = 1
  except models.Contact.DoesNotExist:
    stop_err = 1

  if stop_err:
    await bot.reply_to(message, "Nothing to stop. " + help_message)
    return

  contact.echat_state = SPAWN_CONFIG
  await contact.asave()
  reply = "---ALERT SYSTEM STOPPED---\n"
  reply += "If you want to get the latest patient biometrics, visit https://www.com/patient_monitor"

  await bot.reply_to(message, reply)


@bot.message_handler(commands=["exit"])
async def exit_dialogue(message):

  try:
    contact = await models.Contact.objects.aget(echat_id=message.chat.id)
    if (contact.echat_state in input_states):
      reply = "Exited. Thanks for using Patient Monitoring Service."
      contact.echat_state = SPAWN_CONFIG
      await contact.asave()
    elif (contact.echat_state == ALERTING):
      reply = stop_broadcast_msg
    else:
      reply = help_message
  except models.Contact.DoesNotExist:
    reply = help_message

  await bot.reply_to(message, reply)



@bot.message_handler(commands=["start", "help"])
async def init_dialogue(message):

  wlc = """Welcome to the Patient Monitoring System. I can help you with the initial configuration process to relate this mobile phone to any existent patient in our Databases. In order to get started, I need you to allow me with access to this phone number for registration. If you agree, please tap the button below to share it with me: """

  hlp = "How may I help you? Below there's a list of things I can do for you:" + help_list

  try:
    contact = await models.Contact.objects.aget(echat_id=message.chat.id)
  except models.Contact.DoesNotExist:
    contact = await models.Contact.objects.acreate(echat_id=message.chat.id, chat_username=message.from_user.first_name,
                                                   echat_state=SPAWN_CONFIG, phone_number="", sms_alerts="No")

  markup = None
  if (contact.echat_state in input_states[:8]):
    reply = """You are now within a configuration process. If you want to leave the process without confirming changes, issue '/exit' command. You can restart it later."""
  elif (contact.echat_state == ALERTING):
    reply = stop_broadcast_msg
  elif message.text == "/start":
    qs = await async_Patient_Contact_filter(contact=contact)
    exists = await qs.aexists() # Check whether this phone is already linked to some patient
    if not exists:
      contact.echat_state = WAIT_CONTACT
      await contact.asave()
      markup = types.ReplyKeyboardMarkup(one_time_keyboard=True)
      contact_button = types.KeyboardButton(text="Share this contact", request_contact=True)
      markup.add(contact_button)
      reply = wlc
    else:
      reply = "This phone is already linked to some patient. If you want to add more patients to it, please issue '/add' command or '/help' to get interactive help"
  else: # /help command issued
    contact.echat_state = WAIT_HELP_OPTION
    await contact.asave()
    reply = hlp

  await bot.reply_to(message, reply, reply_markup=markup)
    


def check_state(contact):

  ret = 1
  if (contact.echat_state in input_states[:8]):
    reply = """You are now within a configuration process. If you want to leave the process without confirming changes, issue '/exit' command. You can restart it later. Input: """
  elif (contact.echat_state == ALERTING):
    reply = stop_broadcast_msg
  else:
    ret = 0 # Success
    reply = None

  return ret, reply


async def check_conditions(echat_id):

  try:
    contact = await models.Contact.objects.aget(echat_id=echat_id)
    ret, reply = check_state(contact)
    if ret:
      return 1, contact, reply

    # chat exists on database and it's in a correct state to perform the operation
    qs = await async_Patient_Contact_filter(contact=contact)
    exists = await qs.aexists() # Check whether this chat is already linked to some patient
    if exists:
      return 0, contact, ""
    else:
      return 1, contact, "You must first link this phone to an existing patient. " + help_message
  except models.Contact.DoesNotExist:
    return 1, None, help_message # chat not recorded on Database


@bot.message_handler(commands=["add"])
async def add_patient(message):

  ret, contact, reply = await check_conditions(message.chat.id)
  if ret:
    await bot.reply_to(message, reply)
    return

  # All conditions were met, ask for the patient's name to perform 'add' operation
  contact.echat_state = WAIT_NAME_INPUT
  wait_name_dict[contact.echat_id] = ("add", None)
  await contact.asave()
  reply = "So you want to link more patients to this chat. Please, tell me the complete name of the patient you wish to follow up. If he/she has a compound name, please provide only the first part of it. For example, for patient: 'Charles Robert Johnson Smith', just type 'Charles Johnson Smith: "

  await bot.reply_to(message, reply)



@bot.message_handler(commands=["SMS"])
async def setup_sms(message):

  ret, contact, reply = await check_conditions(message.chat.id)
  if ret:
    await bot.reply_to(message, reply)
    return

  # All conditions were met
  contact.echat_state = WAIT_SMS_OPTION
  await contact.asave()
  reply = """What would you like to do? Type 'enable' or 'en' if you'd like enabling SMS alerts for all patients linked to this phone. Type 'disable' or 'dis' if you wish this feature to be disabled [en/dis] """
  await bot.reply_to(message, reply)


async def check_sms_option(contact, text):

  l = ['enable', 'Enable', 'ENABLE', 'EN', 'en', 'e', 'disable', 'Disable', 'DISABLE', 'DIS', 'dis', 'd']

  if text in l[:6]:
    if contact.echat_state == "Yes":
      reply = "SMS alert system is already enabled for this phone. Exiting configuration process"
    else:
      reply = "SMS alert system succesfully enabled for this phone. " + goodbye_msg
      contact.sms_alerts = "Yes"
  elif text in l[6:]:
    if contact.echat_state == "No":
      reply = "SMS alert system is already disabled on this phone. Exiting configuration process"
    else:
      reply = "SMS alert system succesfully disabled for this phone. " + goodbye_msg
      contact.sms_alerts = "No"
  else:
    reply = "Please type a correct option ('enable' or 'en' / 'disable or 'dis') or issue '/exit' command to leave the process: "
    return contact, reply

  contact.echat_state = SPAWN_CONFIG
  return contact, reply



@bot.message_handler(commands=["del"])
async def delete_number(message):

  ret, contact, reply = await check_conditions(message.chat.id)
  if ret:
    await bot.reply_to(message, reply)
    return

  # All conditions were met, retrieve Patient_Contact objects and ask to confirm 'delete' operation
  l = []
  async for pcontact in models.Patient_Contact.objects.filter(contact=contact):
    l.append(pcontact)
  wait_del_dict[contact.echat_id] = l
  contact.echat_state = WAIT_DEL_CONF
  await contact.asave()
  reply = """Are you sure you want to erase this number from our Database? If you proceed, you won't receive any notifications from Patient Monitoring Service on this phone (neither by Telegram nor SMS systems) anymore. Do you want to proceed? [yes/no]"""

  await bot.reply_to(message, reply)


@bot.message_handler(commands=["show"])
async def show_patients(message):

  try:
    contact = await models.Contact.objects.aget(echat_id=message.chat.id)
    ret, reply = check_state(contact)
    if ret: # Chat's state is not suitable to perform '/show' command
      await bot.reply_to(message, reply)
    else:
      qs = await async_Patient_Contact_filter(contact=contact)
      exists = await qs.aexists()
      if exists:
        reply = "Following patients were configured to be monitored on this phone:\n\n"
        i = 1
        async for pcontact in qs:
          patient = await async_my_get_attr(pcontact, "patient")
          reply += str(i) + ") " + patient.name + " " + patient.surname + ", with dni '" + patient.dni + "'\n"
          i += 1
        if contact.sms_alerts == "Yes":
          sms_alerts = "ENABLED"
        else:
          sms_alerts = "DISABLED"
        reply += "\nSMS alert system: " + sms_alerts + ". That's all. " + goodbye_msg
      else:
        reply = "This chat has not been linked to any patient yet. Issue '/start' command to do so."

      contact.echat_state = SPAWN_CONFIG
      await contact.asave()
      await bot.reply_to(message, reply)
  except models.Contact.DoesNotExist: # chat not recorded on Database
    await bot.reply_to(message, help_message)


async def unfollow_patient(contact, text):

  l = wait_unfollow_dict[contact.echat_id]

  unf_options = []
  for e in range(len(l)):
    unf_options.append(str(e+1))

  if text in unf_options:
    pcontact = l[int(text)-1]
    patient = await async_my_get_attr(pcontact, "patient")
    await pcontact.adelete()
    del(wait_unfollow_dict[contact.echat_id])
    contact.echat_state = SPAWN_CONFIG
    reply = "Follow up discarded for patient '" + patient.name + " " + patient.surname + "' on this phone."
  else:
    reply = "Please provide a valid number from former patient's list or issue '/exit' command to leave the process: "

  return contact, reply


@bot.message_handler(commands=["unfollow"])
async def handle_unfollow(message):

  ret, contact, reply = await check_conditions(message.chat.id)
  if ret:
    await bot.reply_to(message, reply)
    return

  reply = "Following patients are currently linked to this phone:\n"
  i = 1
  l = []
  async for pcontact in models.Patient_Contact.objects.filter(contact=contact):
    patient = await async_my_get_attr(pcontact, "patient")
    reply += str(i) + ") " + patient.name + " " + patient.surname + ", with dni '" + patient.dni + "'\n"
    l.append(pcontact)
    i += 1

  wait_unfollow_dict[contact.echat_id] = l
  reply += "\nWhich one would you like to 'unfollow'? (Type number): "
  contact.echat_state = WAIT_UNFOLLOW_OPTION
  await contact.asave()
  await bot.reply_to(message, reply)


async def confirm_operation(contact, text, chat_state):

  l = ['YES', 'Yes', 'yes', 'Y', 'y', 'NO', 'No', 'no', 'N', 'n']

  if text not in l:
    return contact, "Please confirm operation [yes/no] or issue /exit command to leave the process: "

  if (text in l[:5]): # User confirmed operation
    if (chat_state == WAIT_PATIENT_CONFIRM):
      try:
        command, patient = wait_name_dict[contact.echat_id]
        await models.Patient_Contact.objects.acreate(patient=patient, contact=contact)
        del(wait_name_dict[contact.echat_id])
        reply = "Alright, this telephone has been succesfully registered for patient '" + patient.name + " "
        reply += patient.surname + "', with dni '" + patient.dni + "'. Fron now on, all emergency notifications "
        reply += "from this patient will be addressed to this number. "
        if command == "start":
          contact.echat_state = WAIT_SMS_CONF
          reply += "\nFinally, would you like to enable SMS alert configuration feature, or just dropping it? Your answer will enable or disable this option, respectively, for every single patient linked to this phone. Anyway, you can modify this behaviour later on if you wish [yes/no]"
        else: # performing '/add' command
          contact.echat_state = SPAWN_CONFIG
          reply += goodbye_msg
      except KeyError:
        reply = "There was an error while indexing the patient. Please try again by issuing /start command or /help to get interactive help"
        contact.echat_state = SPAWN_CONFIG
    elif (chat_state == WAIT_SMS_CONF):
      contact.sms_alerts = "Yes"
      contact.echat_state = SPAWN_CONFIG
      reply = "Alright, SMS alert system has also been enabled on this phone. " + goodbye_msg
    elif (chat_state == WAIT_DEL_CONF):
      for pcontact in wait_del_dict[contact.echat_id]:
        await pcontact.adelete() # CASCADE constrain will erase related contact in Patient_Contact table???
      del(wait_del_dict[contact.echat_id])
      await contact.adelete()
      contact = None
      reply = "Phone number deleted from Database. " + goodbye_msg + " Kind Regards"
  elif (text in l[5:]): # User "backed out"
    contact.echat_state = SPAWN_CONFIG
    if (chat_state == WAIT_PATIENT_CONFIRM):
      del(wait_name_dict[contact.echat_id])
      reply = "Registration cancelled. "
    elif (chat_state == WAIT_SMS_CONF):
      contact.sms_alerts = "No"
      reply = "SMS alert system discarded on this phone. "
    elif (chat_state == WAIT_DEL_CONF):
      del(wait_del_dict[contact.echat_id])
      reply = "Phone deletion discarded. "

  return contact, reply


operations = {}
options = []
for e in range(1, 10):
  options.append(str(e))

commands = ["/start", "/stop", "/SMS", "/add", "/unfollow", "/del", "/show", "/help", "/exit"]
functions = [init_dialogue, handle_stop_command, setup_sms, add_patient,
             handle_unfollow, delete_number, show_patients, init_dialogue,
             exit_dialogue]
i = 0
for e in options:
  operations[e] = functions[i], commands[i]
  i += 1

print(operations)


@bot.message_handler(content_types=["contact"])
async def config_number(message):

  try:
    contact = await models.Contact.objects.aget(echat_id=message.chat.id)
    if (contact.echat_state != WAIT_CONTACT):
      await bot.reply_to(message, "Not expecting contact now. " + help_message)
      return
  except models.Contact.DoesNotExist:
    await bot.reply_to(message, help_message)
    return

  # Save contact's phone number
  contact.echat_state = WAIT_NAME_INPUT
  contact.phone_number = message.contact.phone_number
  await contact.asave()

  wait_name_dict[contact.echat_id] = ("start", None)
  reply = """--Contact saved--\nNow, can you please tell me the complete name of the patient you'd like to follow up on this device? If he/she has a compound name, please provide only the first part of it. For example, for patient: 'Charles Robert Johnson Smith', just type 'Charles Johnson Smith':"""

  await bot.reply_to(message, reply)


@bot.message_handler(content_types=["text"])
async def config(message):

  try:
    contact = await models.Contact.objects.aget(echat_id=message.chat.id)
  except models.Contact.DoesNotExist:
    await bot.reply_to(message, help_message)
    return

  if (contact.echat_state == SPAWN_CONFIG):
    reply = help_message
  elif (contact.echat_state == ALERTING):
    reply = stop_broadcast_msg
  elif (contact.echat_state == WAIT_CONTACT):
    contact.echat_state = SPAWN_CONFIG
    reply = "We were expecting for your contact, but got some text input. Plese, restart the process by issuing '/start' command"
  elif (contact.echat_state == WAIT_NAME_INPUT): # Patient configuration interaction
    try:
      l = message.text.split()
      name = l[0]
      surname = ' '.join(l[1:])
      patient = await models.Patient.objects.aget(name=name, surname=surname)
      qs = await async_Patient_Contact_filter(patient=patient, contact=contact)
      exists = await qs.aexists() # Check whether that patient is already linked to this chat
      if not exists:
        command, _ = wait_name_dict[contact.echat_id]
        wait_name_dict[contact.echat_id] = command, patient
        contact.echat_state = WAIT_PATIENT_CONFIRM
        reply = "Quite so, we've found a patient, named '" + patient.name + " " + patient.surname + "',  with dni '"
        reply += patient.dni + "' in our database. Can you please confirm this is the patient you're asking for? [yes/no]"
      else:
        reply = "This number has already been registered for patient '" + patient.name + " " + patient.surname + "'. "
        del(wait_name_dict[contact.echat_id])
        contact.echat_state = SPAWN_CONFIG
    except models.Patient.DoesNotExist:
      reply = "No patients were found with that name. He/She might not be registered in our website yet. Exiting configuration process"
      contact.echat_state = SPAWN_CONFIG
      del(wait_name_dict[contact.echat_id])
    except models.Patient.MultipleObjectsReturned:
      reply = "Several patients were found with that name in our database. Please provide DNI of '" + message.text + "':"
      contact.echat_state = WAIT_DNI_INPUT
  elif (contact.echat_state == WAIT_PATIENT_CONFIRM): # Patient's confirmation expected
    contact, reply = await confirm_operation(contact, message.text, WAIT_PATIENT_CONFIRM)
  elif (contact.echat_state == WAIT_DNI_INPUT): # DNI expected as input
    try:
      patient = await models.Patient.objects.aget(dni=message.text) # Primary key
      qs = await async_Patient_Contact_filter(patient=patient, contact=contact)
      exists = await qs.aexists() # Check whether that patient is already linked to this chat
      if not exists:
        command, _ = wait_name_dict[contact.echat_id]
        wait_name_dict[contact.echat_id] = command, patient
        contact.echat_state = WAIT_PATIENT_CONFIRM
        reply = "Quite so, we've found a patient, named '" + patient.name + " " + patient.surname + "',  with dni '"
        reply += patient.dni + "' in our database. Can you please confirm this is the patient you're asking for? [yes/no]"
      else:
        contact.echat_state = SPAWN_CONFIG
        del(wait_name_dict[contact.echat_id])
        reply = "This number has already been registered for patient '" + patient.name + " " + patient.surname + "', dni '"
        reply += patient.dni + "'. Issue '/show' command if you want to get a list of the patients tracked from this phone."
    except models.Patient.DoesNotExist:
      contact.echat_state = SPAWN_CONFIG
      del(wait_name_dict[contact.echat_id])
      reply = "No matching patient for the dni provided. Please make sure you typed it correctly, then issue the command again "
      reply += "to restart the process"
  elif (contact.echat_state == WAIT_SMS_OPTION):
    contact, reply = await check_sms_option(contact, message.text)
  elif(contact.echat_state == WAIT_SMS_CONF): # SMS confirmation expected
    contact, reply = await confirm_operation(contact, message.text, WAIT_SMS_CONF)
  elif (contact.echat_state == WAIT_DEL_CONF):
    contact, reply = await confirm_operation(contact, message.text, WAIT_DEL_CONF)
  elif (contact.echat_state == WAIT_UNFOLLOW_OPTION):
    contact, reply = await unfollow_patient(contact, message.text)
  elif (contact.echat_state == WAIT_HELP_OPTION):
    if (message.text in options):
      # perform associated command in operations dictionary
      func, command = operations[message.text]
      reply = "Performing " + command + " command..."
      await bot.reply_to(message, reply)
      if (message.text != '9'):  # Keep WAIT_HELP_OPTION chat state on '/exit' command
        contact.echat_state = SPAWN_CONFIG
        await contact.asave()
      msg = message
      msg.text = command
      await func(msg)
      return
    else:
      reply = "Please provide a correct operation number or related command: "

  if (contact != None): # delete_number() returns None contact
    await contact.asave()

  await bot.reply_to(message, reply)


content_types = ["audio, document", "photo", "sticker", "video", "video_note", "voice"
                 "location", "new_chat_members", "left_chat_member", "new_chat_title",
                 "new_chat_photo", "delete_chat_photo", "group_chat_created", 
                 "supergroup_chat_created", "channel_chat_created", "migrate_to_chat_id",
                 "migrate_from_chat_id", "pinned_message", "web_app_data"]

@bot.message_handler(content_types=content_types)
async def default_err(message):
  await bot.reply_to(message, "Support only provided for text input. " + help_message)


def main():

  async def restart_states():
    async for contact in models.Contact.objects.all():
      if (contact.echat_state != ALERTING):
        contact.echat_state = SPAWN_CONFIG
        await contact.asave()

  asyncio.run(restart_states())
  asyncio.run(bot.polling())
#  print("Bot terminated")

p = Process(target=main)
p.start()

print("\n--Yielding control to Django--")
print()
# sys.exit(0)
