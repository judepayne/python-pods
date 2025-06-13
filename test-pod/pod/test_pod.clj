(ns pod.test-pod
  (:refer-clojure :exclude [read read-string])
  (:require [bencode.core :as bencode]
            [cheshire.core :as cheshire]
            [clojure.edn :as edn]
            [clojure.java.io :as io]
            [cognitect.transit :as transit])
  (:import [java.io PushbackInputStream]
           [java.net ServerSocket])
  (:gen-class))

(def debug? true)

(defn debug [& args]
  (when debug?
    (binding [*out* (io/writer "./log.txt" :append true)]
      (apply println (cons (str "pod> " (java.util.Date.) ": ") args)))))


;; ***** CUSTOM EDN READERS *****

(defn read-person-tag [person-data]
  "Custom reader for #person tag"
  (let [{:keys [name age]} person-data]
    {:type "Person"
     :name name
     :age age
     :description (str name " is " age " years old")}))

(defn read-date-tag [date-string]
  "Custom reader for #date tag"
  {:type "Date"
   :value date-string
   :parsed (java.time.LocalDate/parse date-string)})

(def custom-edn-readers
  {'person read-person-tag
   'date read-date-tag})


;; ***** TEST FUNCTIONS *****

(defn deep-merge
  "Recursively merges maps. If a key exists in both maps a
  maps,they are merged recursively. Otherwise, the value f
  takes precedence."
  [m1 m2]
  (cond
    (nil? m1) m2
    (nil? m2) m1
    (and (map? m1) (map? m2))
    (merge-with (fn [v1 v2]
                  (if (and (map? v1) (map? v2))
                    (deep-merge v1 v2)
                    v2))
                m1 m2)
    :else m2))

(defn echo
  "Echoes back the input data unchanged"
  [data]
  (debug "metadata: " (meta data))
  data)


(defn async-countdown
  "Async function that counts down 3, 2, 1 with 1 second delays"
  [opts]
  (let [success-fn (:success opts)
        done-fn (:done opts)]
    (future
      (Thread/sleep 1000)
      (success-fn "3")
      (Thread/sleep 1000) 
      (success-fn "2")
      (Thread/sleep 1000)
      (success-fn "1")
      (done-fn))
    {:status "started"}))

;; **************************

(defn write [stream v]
  (bencode/write-bencode stream v)
  (flush))

(defn read-string [^"[B" v]
  (String. v))

(defn read [stream]
  (bencode/read-bencode stream))

#_(def dependents
  (for [i (range 10)]
    {"name" (str "x" i)
     "code"
     (if-not (zero? i)
       (format "(def x%s (inc x%s))" i (dec i))
       "(def x0 0)")}))

;; Update the transit-json-read function to include UUID support
(defn transit-json-read [^String s]
  (with-open [bais (java.io.ByteArrayInputStream. (.getBytes s "UTF-8"))]
    (let [r (transit/reader bais :json {:handlers
                                        {"local-date-time"
                                         (transit/read-handler
                                          (fn [s]
                                            (java.time.LocalDateTime/parse s)))
                                         "java.array"
                                         (transit/read-handler
                                          (fn [v]
                                            (into-array v)))
                                         "u"  ; UUID handler
                                         (transit/read-handler
                                          (fn [uuid-str]
                                            (java.util.UUID/fromString uuid-str)))}})]
      (transit/read r))))

;; Update the transit-json-write function to include UUID support
(defn transit-json-write [s]
  (with-open [baos (java.io.ByteArrayOutputStream. 4096)]
    (let [w (transit/writer baos :json {:handlers
                                        {java.time.LocalDateTime
                                         (transit/write-handler
                                          "local-date-time"
                                          str)
                                         java.util.UUID
                                         (transit/write-handler
                                          "u"
                                          str)}
                                        :default-handler
                                        (transit/write-handler
                                         (fn [x] (when (.isArray (class x)) "java.array"))
                                         vec)})]
      (transit/write w s)
      (str baos))))

(defn transit-json-write-meta [s]
  (with-open [baos (java.io.ByteArrayOutputStream. 4096)]
    (let [w (transit/writer baos :json {:transform transit/write-meta})]
      (transit/write w s)
      (str baos))))


(defn run-pod [cli-args]
  (let [format (cond (contains? cli-args "--json") :json
                     (contains? cli-args "--transit+json") :transit+json
                     :else :edn)
        write-fn (case format
                   :edn pr-str
                   :json cheshire/generate-string
                   :transit+json transit-json-write)
        read-fn (case format
                  :edn #(edn/read-string {:readers custom-edn-readers} %)
                  :json #(cheshire/parse-string % true)
                  :transit+json transit-json-read)
        socket (= "socket" (System/getenv "BABASHKA_POD_TRANSPORT"))
        [in out] (if socket
                   (let [server (ServerSocket. 0)
                         port (.getLocalPort server)
                         pid (.pid (java.lang.ProcessHandle/current))
                         port-file (io/file (str ".babashka-pod-" pid ".port"))
                         _ (.addShutdownHook (Runtime/getRuntime)
                                             (Thread. (fn [] (.delete port-file))))
                         _ (spit port-file
                                 (str port "\n"))
                         socket (.accept server)
                         in (PushbackInputStream. (.getInputStream socket))
                         out (.getOutputStream socket)]
                     [in out])
                   [(PushbackInputStream. System/in)
                    System/out])]
    (try
      (loop []
        (let [message (try (read in)
                           (catch java.io.EOFException _
                             ::EOF))]
          (when-not (identical? ::EOF message)
            (let [op (get message "op")
                  op (read-string op)
                  op (keyword op)]
              (case op
                :describe
                (do (write out {"format" (case format
                                           :edn "edn"
                                           :json "json"
                                           :transit+json "transit+json")
                                "readers" (case format
                                            :edn {:py
                                                  {"person" "def read_person(data):\n    return {\n        'type': 'Person',\n        'name': data['name'],\n        'age': data['age'],\n        'description': f\"{data['name']} is {data['age']} years old\"\n    }"
                                                   "date" "def read_date(date_str):\n    from datetime import datetime\n    return {\n        'type': 'Date',\n        'value': date_str,\n        'parsed': datetime.fromisoformat(date_str)\n    }"}}
                                            {}) ; No readers for JSON/Transit
                                "namespaces"
                                [{"name" "pod.test-pod"
                                  "vars" [{"name" "add-one"
                                           "meta" "{:doc \"adds one to its integer arg\"}"}
                                          {"name" "deep-merge"}
                                          {"name" "echo"
                                           "meta" "{:doc \"echoes back the input data unchanged\"}"}
                                          {"name" "async-countdown" "async" "true"}
                                          {"name" "echo-meta"
                                           "arg-meta" "true"
                                           "meta" "{:doc \"echoes back data with metadata preserved\"}"}
                                          {"name" "return-python-code"
                                           "meta" "{:doc \"returns Python code to be executed client-side\"}"}
                                          {"name" "define-add2"}]}]
                                "ops" {"shutdown" {}}})
                    (recur))
                :invoke (let [var (-> (get message "var")
                                      read-string
                                      symbol)
                              id (-> (get message "id")
                                     read-string)
                              args (get message "args")
                              args (read-string args)
                              args (read-fn args)]
                          (case var
                            pod.test-pod/add-one
                            (try (let [ret (inc (first args))]
                                   (write out
                                          {"value" (write-fn ret)
                                           "id" id
                                           "status" ["done"]}))
                                 (catch Exception e
                                   (write out
                                          {"ex-data" (write-fn {:args args})
                                           "ex-message" (.getMessage e)
                                           "status" ["done" "error"]
                                           "id" id})))
                            pod.test-pod/deep-merge
                            (try (let [ret (deep-merge (first args) (second args))]
                                   (write out
                                          {"value" (write-fn ret)
                                           "id" id
                                           "status" ["done"]}))
                                 (catch Exception e
                                   (write out
                                          {"ex-data" (write-fn {:args args})
                                           "ex-message" (.getMessage e)
                                           "status" ["done" "error"]
                                           "id" id})))
                            pod.test-pod/echo
                            (try (let [ret (echo (first args))]
                                   (write out
                                          {"value" (write-fn ret)
                                           "id" id
                                           "status" ["done"]}))
                                 (catch Exception e
                                   (write out
                                          {"ex-data" (write-fn {:args args})
                                           "ex-message" (.getMessage e)
                                           "status" ["done" "error"]
                                           "id" id})))
                            pod.test-pod/async-countdown
                            (try 
                              (let [success-fn (fn [value]
                                                 (write out
                                                        {"value" (write-fn value)
                                                         "id" id
                                                         "status" []}))
                                    done-fn (fn []
                                              (write out
                                                     {"id" id
                                                      "status" ["done"]}))
                                    opts {:success success-fn :done done-fn}
                                    ret (async-countdown opts)]
                                (write out
                                       {"value" (write-fn ret)
                                        "id" id
                                        "status" []}))
                              (catch Exception e
                                (write out
                                       {"ex-data" (write-fn {:args args})
                                        "ex-message" (.getMessage e)
                                        "status" ["done" "error"]
                                        "id" id})))
                            pod.test-pod/echo-meta
                            (try
                              (write out
                                     {"id" id
                                      "status" ["done"]
                                      "value"
                                      (case format
                                        :transit+json (transit-json-write-meta (first args))
                                        (write-fn (first args)))})
                              (catch Exception e
                                (write out
                                       {"ex-data" (write-fn {:args args})
                                        "ex-message" (.getMessage e)
                                        "status" ["done" "error"]
                                        "id" id})))
                            pod.test-pod/return-python-code
                            (try 
                              (let [code-type (first args)
                                    ret (case code-type
                                          "function" 
                                          {"code" {"py" "def multiply_by_three(x):\n    return x * 3"
                                                   "clj" "(defn multiply-by-three [x] (* x 3))"}}
                                          
                                          "expression"
                                          {"code" {"py" "result = 42 + 8"
                                                   "clj" "(def result (+ 42 8))"}}
                                          
                                          "complex"
                                          {"code" {"py" "import math\ndef calculate_area(radius):\n    return math.pi * radius * radius\nresult = calculate_area(5)"
                                                   "clj" "(defn calculate-area [radius] (* Math/PI radius radius))\n(def area (calculate-area 5))"}}
                                          
                                          ;; Default case - just python code
                                          {"code" "simple_value = 'Hello from executed Python code!'"})]
                                (write out
                                       {"value" (write-fn ret)
                                        "id" id
                                        "status" ["done"]}))
                              (catch Exception e
                                (write out
                                       {"ex-data" (write-fn {:args args})
                                        "ex-message" (.getMessage e)
                                        "status" ["done" "error"]
                                        "id" id})))
                            pod.test-pod/define-add2
                            (try
                              (let [ret {"code" "(defn add2 [x] (+ 2 x))"}]  ; Fixed [x] instead of [x)
                                (write out
                                       {"value" (write-fn ret)  ; Use write-fn for consistent serialization
                                        "id" id
                                        "status" ["done"]}))
                              (catch Exception e
                                (write out
                                       {"id" id
                                        "ex-data" (write-fn {:args args})
                                        "ex-message" (.getMessage e)
                                        "status" ["done" "error"]})))
                            )
                          (recur))
                :shutdown (System/exit 0)
                :load-ns (let [ns (-> (get message "ns")
                                      read-string
                                      symbol)
                               id (-> (get message "id")
                                      read-string)]
                           (case ns
                             pod.test-pod.loaded
                             (write out
                                    {"status" ["done"]
                                     "id" id
                                     "name" "pod.test-pod.loaded"
                                     "vars" [{"name" "loaded"
                                              "code" "(defn loaded [x] (inc x))"}]})
                             pod.test-pod.loaded2
                             (write out
                                    {"status" ["done"]
                                     "id" id
                                     "name" "pod.test-pod.loaded2"
                                     "vars" [{"name" "x"
                                              "code" "(require '[pod.test-pod.loaded :as loaded])"}
                                             {"name" "loaded"
                                              "code" "(defn loaded [x] (loaded/loaded x))"}]}))
                           (recur)))))))
      (catch Exception e
        (binding [*out* *err*]
          (prn e))))))

(defn -main [& args]
  #_(binding [*out* *err*]
      (prn :args args))
  (when (= "true" (System/getenv "BABASHKA_POD"))
    (run-pod (set args))))
